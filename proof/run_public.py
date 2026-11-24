"""Run the Stock Desk's public transactions on Base Sepolia (testnet only).

    python3 -B proof/run_public.py --rehearse --out /tmp/desk-rehearsal.json   # local fork of Base Sepolia
    python3 -B proof/run_public.py --public   --out demo/public-sepolia.json    # public Base Sepolia

Three transactions, all from one testnet-only desk wallet:
1. deploy StockDeskLog, the desk's public spend record (once; the address is kept in --state)
2. pay for the weekend price check over x402 with Circle test USDC (EIP-3009 authorization)
3. record the desk's decision for the story spend in StockDeskLog

The desk wallet key is read from a local file (BASE_DESK_KEY_FILE). It is never printed or written.
Every write first checks that the chain is Base Sepolia (84532). Base mainnet is refused.
"""
import argparse
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collateral_card import x402  # noqa: E402
from collateral_card.demo import X402_AMOUNT, _free_port, _header, _http_get, _rpc  # noqa: E402
from collateral_card.desk import DEMO_BOOK, DEMO_LIMITS, check_spend  # noqa: E402
from collateral_card.paid_quote import DEMO_REQUEST, weekend_quote  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_RPC = "https://sepolia.base.org"
CHAIN_ID = 84532
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # Circle test USDC on Base Sepolia
EXPLORER = "https://sepolia.basescan.org"
SECRETS = Path.home() / ".local/state/fleet/secrets"
KEY_FILE = Path(os.environ.get("BASE_DESK_KEY_FILE", SECRETS / "base-desk-testnet-24nov.json"))
SELLER_FILE = Path(os.environ.get("BASE_DESK_SELLER_FILE", SECRETS / "base-desk-testnet-seller-24nov.json"))
ARTIFACT = json.loads((ROOT / "contracts/StockDeskLog.json").read_text())
WEEKEND, AS_OF, STORY_SPEND = "2026-11-06", "2026-11-09T00:05:00Z", "40.00"
ACTIONS = {"ALLOW": 1, "CUT": 2, "REFUSE": 3}
MIN_GAS_WEI = 10**14  # 0.0001 ETH; three transactions use far less at Base Sepolia gas prices


class Key:
    """Holds a private key without ever exposing it in repr, logs or errors."""

    def __init__(self, path):
        data = json.loads(Path(path).read_text())
        data = data[0] if isinstance(data, list) else data
        self._secret = data["private_key"]
        self.address = data["address"]

    def __repr__(self):
        return f"Key({self.address})"


def _scrub(text, keys):
    for key in keys:
        text = text.replace(key._secret, "<key>").replace(key._secret.removeprefix("0x"), "<key>")
    return text


def cast(args, key=None, check=True):
    cmd = ["cast", *args]
    if key is not None:
        at = 3 if args[0] == "wallet" else 2  # options go before positionals such as --create CODE
        cmd[at:at] = ["--private-key", key._secret]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        keys = [key] if key else []
        raise RuntimeError(_scrub(f"cast {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}", keys))
    return proc


def require_sepolia(rpc):
    chain = int(_rpc(rpc, "eth_chainId", []), 16)
    if chain != CHAIN_ID:
        raise SystemExit(f"Refusing to write: chain {chain} is not Base Sepolia ({CHAIN_ID}).")


def send(rpc, key, to, sig, *args):
    require_sepolia(rpc)
    proc = cast(["send", to, sig, *args, "--rpc-url", rpc, "--json"], key=key, check=False)
    if proc.returncode != 0:
        return {"status": "0x0", "error": _scrub((proc.stderr or proc.stdout).strip(), [key])}
    return json.loads(proc.stdout)


def deploy(rpc, key):
    require_sepolia(rpc)
    args = cast(["abi-encode", "constructor(address)", key.address]).stdout.strip()
    code = ARTIFACT["bytecode"] + args.removeprefix("0x")
    proc = cast(["send", "--rpc-url", rpc, "--json", "--create", code], key=key)
    receipt = json.loads(proc.stdout)
    if int(receipt["status"], 16) != 1:
        raise RuntimeError("StockDeskLog deployment reverted.")
    return receipt


def call(rpc, to, sig, *args):
    return cast(["call", to, sig, *args, "--rpc-url", rpc]).stdout.strip()


def uint(rpc, to, sig, *args):
    return int(call(rpc, to, sig, *args).split()[0])


def eth_balance(rpc, addr):
    return int(_rpc(rpc, "eth_getBalance", [addr, "latest"]), 16)


def block_time(rpc):
    return int(_rpc(rpc, "eth_getBlockByNumber", ["latest", False])["timestamp"], 16)


def sign_payment(rpc, key, required):
    accepted = required["accepts"][0]
    now = block_time(rpc)
    nonce = "0x" + os.urandom(32).hex()
    valid_after, valid_before = now - 10, now + int(accepted["maxTimeoutSeconds"])
    message = {"from": key.address, "to": accepted["payTo"], "value": accepted["amount"],
               "validAfter": str(valid_after), "validBefore": str(valid_before), "nonce": nonce}
    typed = {
        "types": {
            "EIP712Domain": [{"name": n, "type": t} for n, t in (
                ("name", "string"), ("version", "string"), ("chainId", "uint256"), ("verifyingContract", "address"))],
            "TransferWithAuthorization": [{"name": n, "type": t} for n, t in (
                ("from", "address"), ("to", "address"), ("value", "uint256"),
                ("validAfter", "uint256"), ("validBefore", "uint256"), ("nonce", "bytes32"))],
        },
        "primaryType": "TransferWithAuthorization",
        "domain": {"name": accepted["extra"]["name"], "version": accepted["extra"]["version"],
                   "chainId": int(accepted["network"].split(":")[1]), "verifyingContract": accepted["asset"]},
        "message": message,
    }
    sig = cast(["wallet", "sign", "--data", json.dumps(typed)], key=key).stdout.strip()
    return {"x402Version": required["x402Version"], "resource": required["resource"], "accepted": accepted,
            "payload": {"signature": sig, "authorization": message}}


def quote_server(rpc, relayer, terms):
    """Loopback x402 seller. Settlement is sent by the desk wallet acting as relayer and pays the seller."""
    body = json.dumps(weekend_quote(*DEMO_REQUEST)).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _reply(self, status, headers=None, raw=b"{}"):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _required(self):
            url = f"http://127.0.0.1:{self.server.server_port}/quote"
            return {x402.HEADER_REQUIRED: x402.encode_header(x402.payment_required(terms, url))}

        def do_GET(self):
            if self.path != "/quote":
                return self._reply(404)
            header = self.headers.get(x402.HEADER_SIGNATURE)
            if not header:
                return self._reply(402, self._required())
            payment = x402.decode_header(header)
            ok, why = x402.check_payment(payment, terms, block_time(rpc))
            auth = payment["payload"]["authorization"]
            if ok:
                used = call(rpc, USDC, "authorizationState(address,bytes32)(bool)", auth["from"], auth["nonce"])
                if used == "true":
                    ok, why = False, "authorization already used"
            if not ok:
                failed = {"success": False, "errorReason": why, "transaction": "", "network": terms["network"]}
                return self._reply(402, {**self._required(), x402.HEADER_RESPONSE: x402.encode_header(failed)})
            sig = payment["payload"]["signature"].removeprefix("0x")
            r, s, v = "0x" + sig[:64], "0x" + sig[64:128], str(int(sig[128:130], 16))
            receipt = send(
                rpc, relayer, USDC,
                "transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)",
                auth["from"], auth["to"], str(auth["value"]), str(auth["validAfter"]), str(auth["validBefore"]),
                auth["nonce"], v, r, s,
            )
            if int(receipt.get("status", "0x0"), 16) != 1:
                failed = {"success": False, "errorReason": "settlement_reverted", "transaction": "",
                          "network": terms["network"]}
                return self._reply(402, {**self._required(), x402.HEADER_RESPONSE: x402.encode_header(failed)})
            settled = {"success": True, "transaction": receipt["transactionHash"], "network": terms["network"],
                       "payer": auth["from"]}
            self._reply(200, {x402.HEADER_RESPONSE: x402.encode_header(settled)}, body)

    server = HTTPServer(("127.0.0.1", _free_port()), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@contextmanager
def rehearsal_fork(desk, seller):
    """Local copy of Base Sepolia. Only here may the script mint test USDC or set balances."""
    from run_sepolia import sepolia_fork
    with sepolia_fork() as rpc:
        _rpc(rpc, "anvil_setBalance", [desk.address, hex(10**16)])
        master = call(rpc, USDC, "masterMinter()(address)")
        minter = "0x" + "11" * 20
        for addr in (master, minter):
            _rpc(rpc, "anvil_impersonateAccount", [addr])
            _rpc(rpc, "anvil_setBalance", [addr, hex(10**18)])
        for frm, sig, args in ((master, "configureMinter(address,uint256)", [minter, str(X402_AMOUNT)]),
                               (minter, "mint(address,uint256)", [desk.address, str(X402_AMOUNT)])):
            cast(["send", USDC, sig, *args, "--from", frm, "--unlocked", "--rpc-url", rpc, "--json"])
        yield rpc


def run(rpc, desk, seller, state_path, public):
    eth_before = eth_balance(rpc, desk.address)
    usdc = lambda a: uint(rpc, USDC, "balanceOf(address)(uint256)", a)  # noqa: E731
    if eth_before < MIN_GAS_WEI:
        raise SystemExit(f"Desk wallet {desk.address} has {eth_before} wei. Waiting for test ETH.")
    if usdc(desk.address) < X402_AMOUNT:
        raise SystemExit(f"Desk wallet {desk.address} holds under 0.05 test USDC. Waiting for the faucet.")
    txs = {}

    # 1. The public spend record, deployed once.
    state = json.loads(state_path.read_text()) if public and state_path.exists() else {}
    log = state.get("StockDeskLog")
    if log and _rpc(rpc, "eth_getCode", [log, "latest"]) not in ("0x", None):
        txs["deploy"] = state.get("deploy_tx")
    else:
        receipt = deploy(rpc, desk)
        log, txs["deploy"] = receipt["contractAddress"], receipt["transactionHash"]
        if public:
            state_path.write_text(json.dumps({"StockDeskLog": log, "deploy_tx": txs["deploy"]}, indent=2) + "\n")
    if call(rpc, log, "desk()(address)").lower() != desk.address.lower():
        raise RuntimeError("StockDeskLog does not name the desk wallet as its writer.")

    # 2. The paid price check: 402 challenge, signed test USDC authorization, settlement, repeat refused.
    terms = x402.requirements(seller.address, X402_AMOUNT, network=f"eip155:{CHAIN_ID}", asset=USDC,
                              token_name="USDC")
    server = quote_server(rpc, desk, terms)
    url = f"http://127.0.0.1:{server.server_port}/quote"
    try:
        buyer0, seller0 = usdc(desk.address), usdc(seller.address)
        challenge, _, challenge_headers = _http_get(url)
        required = x402.decode_header(_header(challenge_headers, x402.HEADER_REQUIRED))
        headers = {x402.HEADER_SIGNATURE: x402.encode_header(sign_payment(rpc, desk, required))}
        paid, quote_body, paid_headers = _http_get(url, headers)
        settled = x402.decode_header(_header(paid_headers, x402.HEADER_RESPONSE))
        if paid != 200 or not settled.get("success"):
            raise RuntimeError(f"Paid check failed ({paid}): {settled.get('errorReason')}")
        txs["payment"] = settled["transaction"]
        buyer1, seller1 = usdc(desk.address), usdc(seller.address)
        retry, _, retry_headers = _http_get(url, headers)
        retry_reason = x402.decode_header(_header(retry_headers, x402.HEADER_RESPONSE) or "e30=").get("errorReason")
        seller2 = usdc(seller.address)
    finally:
        server.shutdown()
        server.server_close()
    quote = json.loads(quote_body)

    # 3. The desk's decision for the story spend, recorded on chain with the payment it relied on.
    decision = check_spend(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF, STORY_SPEND)
    record = {"decision": decision, "quote": quote, "payment_tx": txs["payment"]}
    digest = "0x" + hashlib.sha3_256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    cents = lambda usd: str(round(float(usd) * 100))  # noqa: E731
    allowed = decision.get("allowed_usd", decision["amount_usd"] if decision["action"] == "ALLOW" else "0")
    count0 = uint(rpc, log, "count()(uint256)")
    receipt = send(rpc, desk, log, "record(bytes32,uint8,uint256,uint256,bytes32,string)",
                   digest, str(ACTIONS[decision["action"]]), cents(decision["amount_usd"]), cents(allowed),
                   txs["payment"], decision["reason"])
    if int(receipt.get("status", "0x0"), 16) != 1:
        raise RuntimeError(f"Spend record reverted: {receipt.get('error', '')}")
    txs["record"] = receipt["transactionHash"]
    count1 = uint(rpc, log, "count()(uint256)")

    checks = {
        "challenge_is_402": challenge == 402,
        "paid_is_200": paid == 200,
        "buyer_paid_exact": buyer0 - buyer1 == X402_AMOUNT,
        "seller_got_exact": seller1 - seller0 == X402_AMOUNT,
        "repeat_refused": retry == 402 and seller2 == seller1,
        "record_added_one": count1 == count0 + 1,
        "record_event_emitted": len(receipt.get("logs", [])) == 1
            and receipt["logs"][0]["address"].lower() == log.lower(),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Checks failed: {[k for k, v in checks.items() if not v]}")
    out = {
        "mode": "public Base Sepolia" if public else "rehearsal on a local Base Sepolia fork",
        "chain_id": CHAIN_ID,
        "desk_wallet": desk.address,
        "seller": seller.address,
        "test_usdc": USDC,
        "spend_record_contract": log,
        "transactions": txs,
        "paid_check": {"http": [challenge, paid, retry], "repeat_reason": retry_reason,
                       "price_raw": X402_AMOUNT, "gap_percent": quote.get("pool_minus_lending_percent")},
        "decision": {k: decision[k] for k in ("action", "amount_usd", "allowed_usd", "reason") if k in decision},
        "record_digest_sha3_256": digest,
        "checks": checks,
        "labels": ["testnet only", "historical replay prices", "demo book", "the loan is simulated",
                   "no trades are placed"],
    }
    if public:
        out["explorer"] = {
            "desk_wallet": f"{EXPLORER}/address/{desk.address}",
            "spend_record_contract": f"{EXPLORER}/address/{log}",
            **{name: f"{EXPLORER}/tx/{tx}" for name, tx in txs.items() if tx},
        }
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rehearse", action="store_true")
    mode.add_argument("--public", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=ROOT / "demo/public-sepolia-state.json")
    args = parser.parse_args()
    desk, seller = Key(KEY_FILE), Key(SELLER_FILE)
    ctx = rehearsal_fork(desk, seller) if args.rehearse else nullcontext(PUBLIC_RPC)
    with ctx as rpc:
        result = run(rpc, desk, seller, args.state, args.public)
    text = json.dumps(result, indent=2) + "\n"
    for key in (desk, seller):
        assert key._secret.removeprefix("0x") not in text
    args.out.write_text(text, encoding="utf-8")
    print(f"PASS · {result['mode']}: log {result['spend_record_contract']}, "
          f"{len(result['transactions'])} transactions, decision {result['decision']['action']}.")


if __name__ == "__main__":
    main()
