"""Local Base fork demo: guarded Mag7 position survives the Sunday reopen; control does not."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from collateral_card.guard import NotLocalRPC, require_local
from collateral_card import rule, x402

# ---- Proven addresses (manual spike) ------------------------------------------------------------
SPOKE = "0x17905Db0e4A3514467539956c084180616AE7B8D"
HUB = "0xa4d5947eb727a052bae69c593ffc84247ec9864e"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
NVDAC = "0xb20000000000000000000078ee7ce2fe4908108c"
FEED = "0x04689a41629776563E6822F76f2e57D148d28513"
ORACLE = "0xaBaf048fD7675Ea34a84332371ffd5D55E322A47"
DEX_POOL = "0xf668e21993f0acd7ab00bb1cfbaed0df28a3c8ec"
INPUTS = json.loads((Path(__file__).resolve().parents[1] / "inputs.json").read_text())
CHAIN_ID = INPUTS["chain_id"]
RESERVE_NVDAC = 5
RESERVE_USDC = 7
SUPPLY_RAW = INPUTS["starting_collateral_raw"]
X402_AMOUNT = INPUTS["quote_price_raw"]
MAX_UINT = (1 << 256) - 1
GAS_LIMIT = 3_000_000
START_HF = INPUTS["target_starting_health"]
CF = INPUTS["collateral_factor"]
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
FORK_URL_READ = "https://mainnet.base.org"  # read-only fork source for anvil; never a write target


class _RemoteWriteCounter:
    def __init__(self):
        self.count = 0

    def check(self, url: str) -> str:
        try:
            return require_local(url)
        except NotLocalRPC:
            self.count += 1
            raise


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(cmd, check=True, **kwargs):
    return subprocess.run(cmd, check=check, capture_output=True, text=True, **kwargs)


def _rpc(url: str, method: str, params, counter: _RemoteWriteCounter | None = None, write=False):
    if write:
        if counter is None:
            require_local(url)
        else:
            counter.check(url)
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "curl/8.7.1"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.load(resp)
    if "error" in body:
        raise RuntimeError(f"{method} error: {body['error']}")
    return body["result"]


def _cast(rpc: str, args: list[str], counter: _RemoteWriteCounter, write=False):
    if write:
        counter.check(rpc)
    cmd = ["cast", *args, "--rpc-url", rpc]
    return _run(cmd)


def _cast_send(rpc: str, frm: str, to: str, sig: str, *sig_args: str, counter: _RemoteWriteCounter):
    counter.check(rpc)
    cmd = [
        "cast", "send", to, sig, *sig_args,
        "--from", frm, "--unlocked", f"--gas-limit={GAS_LIMIT}",
        "--rpc-url", rpc, "--json",
    ]
    proc = _run(cmd, check=False)
    if proc.returncode != 0:
        return {"status": "0x0", "error": (proc.stderr or proc.stdout or "").strip()}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "0x0", "error": proc.stdout.strip()}


def _tx_ok(receipt: dict) -> bool:
    return int(receipt.get("status", "0x0"), 16) == 1


def _pinned_block() -> int:
    number = INPUTS["fork_block"]
    block = _rpc(FORK_URL_READ, "eth_getBlockByNumber", [hex(number), False])
    if not block or block["hash"] != INPUTS["fork_block_hash"]:
        raise RuntimeError("The upstream did not return the recorded Base block")
    return number


def _read_hub_nvdac_balance(block: int) -> int:
    # Read the original token at the pinned block before the fork replaces its code.
    result = _run([
        "cast", "call", NVDAC, "balanceOf(address)(uint256)", HUB,
        "--block", str(block), "--rpc-url", FORK_URL_READ,
    ])
    return int(result.stdout.split()[0])


def _solc_bin() -> str:
    solc = shutil.which("solc")
    if solc:
        return solc
    raise RuntimeError("Install native solc 0.8.20 and add it to PATH.")


def _build_standins() -> dict[str, str]:
    """Compile the two stand-ins via svm solc (forge's compiler). Reuse forge artifacts if present."""
    out: dict[str, str] = {}
    for name in ("MintableERC20", "SettableFeed"):
        path = os.path.join(PACKAGE_DIR, "out", f"{name}.sol", f"{name}.json")
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    art = json.load(f)
                bytecode = art["deployedBytecode"]["object"]
                if not bytecode.startswith("0x"):
                    bytecode = "0x" + bytecode
                out[name] = bytecode
            except (OSError, KeyError, json.JSONDecodeError, TypeError):
                out.clear()
                break
    if len(out) == 2:
        return out

    # forge build hangs in this worktree; compile with the same solc forge would use.
    solc = _solc_bin()
    dest = os.path.join(PACKAGE_DIR, "out", "solc")
    os.makedirs(dest, exist_ok=True)
    sources = [
        os.path.join(PACKAGE_DIR, "contracts", "MintableERC20.sol"),
        os.path.join(PACKAGE_DIR, "contracts", "SettableFeed.sol"),
    ]
    _run([solc, "--bin-runtime", "--optimize", "--optimize-runs", "200", "-o", dest, "--overwrite", *sources])
    for name in ("MintableERC20", "SettableFeed"):
        with open(os.path.join(dest, f"{name}.bin-runtime")) as f:
            hexdata = f.read().strip()
        if not hexdata.startswith("0x"):
            hexdata = "0x" + hexdata
        out[name] = hexdata
    return out


def _accounts(rpc: str) -> list[str]:
    return _rpc(rpc, "eth_accounts", [])


def _block_timestamp(rpc: str) -> int:
    block = _rpc(rpc, "eth_getBlockByNumber", ["latest", False])
    return int(block["timestamp"], 16)


def _set_code(rpc: str, addr: str, code: str, counter: _RemoteWriteCounter):
    _rpc(rpc, "anvil_setCode", [addr, code], counter=counter, write=True)


def _set_balance(rpc: str, addr: str, wei: int, counter: _RemoteWriteCounter):
    _rpc(rpc, "anvil_setBalance", [addr, hex(wei)], counter=counter, write=True)


def _impersonate(rpc: str, addr: str, counter: _RemoteWriteCounter):
    _rpc(rpc, "anvil_impersonateAccount", [addr], counter=counter, write=True)


def _stop_impersonate(rpc: str, addr: str, counter: _RemoteWriteCounter):
    _rpc(rpc, "anvil_stopImpersonatingAccount", [addr], counter=counter, write=True)


def _call_uint(rpc: str, to: str, sig: str, *args: str) -> int:
    out = _run(["cast", "call", to, sig, *args, "--rpc-url", rpc])
    return int(out.stdout.strip().split()[0])


def _user_account(rpc: str, user: str) -> dict:
    out = _run(
        [
            "cast", "call", SPOKE,
            "getUserAccountData(address)(uint256,uint256,uint256,uint256,uint256,uint256,uint256)",
            user, "--rpc-url", rpc,
        ]
    )
    parts = [int(x) for x in out.stdout.replace("[", " ").replace("]", " ").split() if x.isdigit() or (x.startswith("-") and x[1:].isdigit())]
    # cast prints each tuple field on its own line, sometimes with scientific notes — parse lines
    vals = []
    for line in out.stdout.strip().splitlines():
        token = line.strip().split()[0]
        vals.append(int(token, 0) if token.startswith("0x") else int(token))
    return {
        "hf": vals[2] / 1e18,
        "collateral_usd": vals[3] / 1e26,
        "raw": vals,
    }


def _supplied(rpc: str, user: str) -> int:
    return _call_uint(rpc, SPOKE, "getUserSuppliedAssets(uint256,address)(uint256)", str(RESERVE_NVDAC), user)


def _set_feed(rpc: str, price: float, deployer: str, counter: _RemoteWriteCounter):
    raw = int(round(price * 1e8))
    receipt = _cast_send(rpc, deployer, FEED, "setAnswer(int256)", str(raw), counter=counter)
    if not _tx_ok(receipt):
        raise RuntimeError(f"setAnswer failed: {receipt}")


def _sign_eip3009(rpc: str, payer: str, accepted: dict, valid_after: int, valid_before: int, nonce: str) -> str:
    typed = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "primaryType": "TransferWithAuthorization",
        "domain": {
            "name": accepted["extra"]["name"],
            "version": accepted["extra"]["version"],
            "chainId": int(accepted["network"].split(":")[1]),
            "verifyingContract": accepted["asset"],
        },
        "message": {
            "from": payer,
            "to": accepted["payTo"],
            "value": accepted["amount"],
            "validAfter": str(valid_after),
            "validBefore": str(valid_before),
            "nonce": nonce,
        },
    }
    # eth_signTypedData_v4 is a local anvil signing call (dev key); still only against loopback.
    require_local(rpc)
    result = _rpc(rpc, "eth_signTypedData_v4", [payer, typed])
    return result


def _split_sig(sig: str) -> tuple[int, str, str]:
    h = sig[2:] if sig.startswith("0x") else sig
    r = "0x" + h[0:64]
    s = "0x" + h[64:128]
    v = int(h[128:130], 16)
    return v, r, s


def _start_x402_server(rpc: str, payee: str, terms: dict, counter: _RemoteWriteCounter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _reply(self, status: int, headers: dict | None = None, body: bytes = b"{}"):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _refuse(self, reason: str, payer: str = ""):
            required = x402.payment_required(terms, f"http://{self.headers.get('Host')}/quote")
            settled = {"success": False, "errorReason": reason, "transaction": "",
                       "network": terms["network"], "payer": payer}
            self._reply(402, {x402.HEADER_REQUIRED: x402.encode_header(required),
                              x402.HEADER_RESPONSE: x402.encode_header(settled)})

        def do_GET(self):
            if self.path.split("?")[0] != "/quote":
                self._reply(404)
                return
            header = self.headers.get(x402.HEADER_SIGNATURE)
            if not header:
                required = x402.payment_required(terms, f"http://{self.headers.get('Host')}/quote")
                self._reply(402, {x402.HEADER_REQUIRED: x402.encode_header(required)})
                return
            try:
                payment = x402.decode_header(header)
            except ValueError:
                self._refuse("invalid_payload")
                return
            ok, why = x402.check_payment(payment, terms, _block_timestamp(rpc))
            auth = (payment.get("payload") or {}).get("authorization") or {}
            if not ok:
                self._refuse(why, str(auth.get("from", "")))
                return
            v, r, s = _split_sig(payment["payload"]["signature"])
            receipt = _cast_send(
                rpc, payee, USDC,
                "transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)",
                auth["from"], auth["to"], str(auth["value"]), str(auth["validAfter"]),
                str(auth["validBefore"]), auth["nonce"], str(v), r, s, counter=counter,
            )
            if not _tx_ok(receipt):
                self._refuse("settlement_reverted", auth["from"])
                return
            settled = {"success": True, "transaction": receipt.get("transactionHash", ""),
                       "network": terms["network"], "payer": auth["from"]}
            self._reply(200, {x402.HEADER_RESPONSE: x402.encode_header(settled)}, b'{"ok":true}')

    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


def _http_get(url: str, headers: dict | None = None) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), dict(resp.headers.items())
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers.items())


def _header(headers: dict, name: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _signed_payment(rpc: str, required: dict, payer: str, signer: str) -> dict:
    """Build the PaymentPayload from the server's own 402 terms."""
    accepted = required["accepts"][0]
    now = _block_timestamp(rpc)
    nonce = "0x" + os.urandom(32).hex()
    valid_after = now - 10
    valid_before = now + int(accepted["maxTimeoutSeconds"])
    # The EIP-712 message names the signer as `from`, so a wrong signer cannot satisfy `payer`.
    sig = _sign_eip3009(rpc, signer, accepted, valid_after, valid_before, nonce)
    return {
        "x402Version": required["x402Version"],
        "resource": required["resource"],
        "accepted": accepted,
        "payload": {
            "signature": sig,
            "authorization": {
                "from": payer, "to": accepted["payTo"], "value": accepted["amount"],
                "validAfter": str(valid_after), "validBefore": str(valid_before), "nonce": nonce,
            },
        },
    }


def _x402_flow(rpc: str, server_base: str, payer: str, payee: str) -> dict:
    first_status, _, first_headers = _http_get(f"{server_base}/quote")
    required = x402.decode_header(_header(first_headers, x402.HEADER_REQUIRED))
    payment = _signed_payment(rpc, required, payer, payer)
    before = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", payee)
    paid_status, _, paid_headers = _http_get(
        f"{server_base}/quote", headers={x402.HEADER_SIGNATURE: x402.encode_header(payment)},
    )
    after = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", payee)
    settled = _header(paid_headers, x402.HEADER_RESPONSE)
    return {
        "protocol": required["x402Version"],
        "first_status": first_status,
        "paid_status": paid_status,
        "payee_delta_raw": after - before,
        "settlement": x402.decode_header(settled) if settled else None,
    }


def _forged_payment_status(rpc: str, server_base: str, real_payer: str, wrong_signer: str) -> int:
    _, _, headers = _http_get(f"{server_base}/quote")
    required = x402.decode_header(_header(headers, x402.HEADER_REQUIRED))
    payment = _signed_payment(rpc, required, real_payer, wrong_signer)
    status, _, _ = _http_get(
        f"{server_base}/quote", headers={x402.HEADER_SIGNATURE: x402.encode_header(payment)},
    )
    return status


def _open_position(rpc: str, user: str, borrow_raw: int, counter: _RemoteWriteCounter):
    for token in (NVDAC, USDC):
        r = _cast_send(rpc, user, token, "approve(address,uint256)", SPOKE, str(MAX_UINT), counter=counter)
        if not _tx_ok(r):
            raise RuntimeError(f"approve failed for {token}: {r}")
    r = _cast_send(rpc, user, SPOKE, "supply(uint256,uint256,address)", str(RESERVE_NVDAC), str(SUPPLY_RAW), user, counter=counter)
    if not _tx_ok(r):
        raise RuntimeError(f"supply failed: {r}")
    r = _cast_send(
        rpc, user, SPOKE, "setUsingAsCollateral(uint256,bool,address)",
        str(RESERVE_NVDAC), "true", user, counter=counter,
    )
    if not _tx_ok(r):
        raise RuntimeError(f"setUsingAsCollateral failed: {r}")
    r = _cast_send(
        rpc, user, SPOKE, "borrow(uint256,uint256,address)",
        str(RESERVE_USDC), str(borrow_raw), user, counter=counter,
    )
    if not _tx_ok(r):
        raise RuntimeError(f"borrow failed: {r}")


def _liquidate(rpc: str, liquidator: str, user: str, counter: _RemoteWriteCounter) -> str:
    r = _cast_send(
        rpc, liquidator, SPOKE,
        "liquidationCall(uint256,uint256,address,uint256,bool)",
        str(RESERVE_NVDAC), str(RESERVE_USDC), user, str(MAX_UINT), "false",
        counter=counter,
    )
    if _tx_ok(r):
        return "liquidated"
    err = (r.get("error") or "") + json.dumps(r)
    if "HealthFactorNotBelowThreshold" in err:
        return "refused"
    # cast sometimes only prints the custom error selector
    # HealthFactorNotBelowThreshold() selector:
    sel = _run(["cast", "sig", "HealthFactorNotBelowThreshold()"]).stdout.strip()
    if sel and sel[2:10].lower() in err.lower():
        return "refused"
    raise RuntimeError(f"liquidation unexpected failure: {r}")


def _fixture_row(weekend: str, token: str) -> tuple[dict, float]:
    if (weekend, token) != (INPUTS["weekend_friday"], INPUTS["symbol"]):
        raise ValueError(f"no fixture row for {token} {weekend}")
    return INPUTS, INPUTS["band_pts"]
