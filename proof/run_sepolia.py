"""Exercise the quote checkout with Circle test USDC on a disposable Base Sepolia fork."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import time

from collateral_card import x402
from collateral_card.demo import (
    X402_AMOUNT, _RemoteWriteCounter, _accounts, _call_uint, _cast,
    _cast_send, _free_port, _header, _http_get, _impersonate, _rpc,
    _set_balance, _signed_payment, _start_x402_server, _stop_impersonate, _tx_ok,
)

UPSTREAM = "https://sepolia.base.org"
CHAIN_ID = 84532
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
BLOCK = 62992943
BLOCK_HASH = "0xdc27af8b8caaaf3a45aed0a2fbcc66308783afffad353f22534d803d166acf1a"


@contextmanager
def sepolia_fork():
    block = _rpc(UPSTREAM, "eth_getBlockByNumber", [hex(BLOCK), False])
    if not block or block["hash"] != BLOCK_HASH:
        raise RuntimeError("Base Sepolia did not return the pinned source block.")
    port = _free_port()
    rpc = f"http://127.0.0.1:{port}"
    with subprocess.Popen(
        ["anvil", "--host", "127.0.0.1", "--port", str(port), "--fork-url", UPSTREAM,
         "--fork-block-number", str(BLOCK), "--chain-id", str(CHAIN_ID),
         "--optimism", "--hardfork", "jovian", "--silent"],
        stdout=subprocess.DEVNULL,
    ) as process:
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Anvil exited before the fork was ready.")
                try:
                    chain_id = _rpc(rpc, "eth_chainId", [])
                except OSError:
                    time.sleep(0.15)
                    continue
                if int(chain_id, 16) != CHAIN_ID:
                    raise RuntimeError("The local fork is not Base Sepolia.")
                break
            else:
                raise RuntimeError("Timed out waiting for Anvil.")
            yield rpc
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def seed_buyer(rpc, minter, buyer, counter):
    # The admin impersonation is confined to the disposable testnet copy.
    master = _cast(rpc, ["call", USDC, "masterMinter()(address)"], counter).stdout.strip()
    _impersonate(rpc, master, counter)
    try:
        _set_balance(rpc, master, 10**18, counter)
        configure = _cast_send(
            rpc, master, USDC, "configureMinter(address,uint256)", minter, str(X402_AMOUNT),
            counter=counter,
        )
        if not _tx_ok(configure):
            raise RuntimeError("Could not configure the fork's test mint.")
    finally:
        _stop_impersonate(rpc, master, counter)
    mint = _cast_send(rpc, minter, USDC, "mint(address,uint256)", buyer, str(X402_AMOUNT), counter=counter)
    if not _tx_ok(mint):
        raise RuntimeError("Could not seed the fork buyer with test USDC.")


def run():
    counter = _RemoteWriteCounter()
    with sepolia_fork() as rpc:
        minter, buyer, seller = _accounts(rpc)[:3]
        seed_buyer(rpc, minter, buyer, counter)
        terms = x402.requirements(
            seller, X402_AMOUNT, network=f"eip155:{CHAIN_ID}", asset=USDC, token_name="USDC",
        )
        server, base = _start_x402_server(rpc, seller, terms, counter)
        try:
            return checkout(rpc, base + "/quote", buyer, seller, counter)
        finally:
            server.shutdown()
            server.server_close()


def checkout(rpc, url, buyer, seller, counter):
    def balance(account):
        return _call_uint(rpc, USDC, "balanceOf(address)(uint256)", account)

    buyer_before, seller_before = balance(buyer), balance(seller)
    challenge, challenge_body, challenge_headers = _http_get(url)
    if challenge != 402 or json.loads(challenge_body):
        raise RuntimeError(f"Expected a payment challenge without a quote, received {challenge}.")
    required = x402.decode_header(_header(challenge_headers, x402.HEADER_REQUIRED))
    payment = _signed_payment(rpc, required, buyer, buyer)
    headers = {x402.HEADER_SIGNATURE: x402.encode_header(payment)}
    paid, body, paid_headers = _http_get(url, headers)
    if paid != 200:
        failure = _header(paid_headers, x402.HEADER_RESPONSE)
        details = x402.decode_header(failure) if failure else {}
        raise RuntimeError(f"Quote payment failed ({paid}): {details.get('errorReason')}")
    settled = x402.decode_header(_header(paid_headers, x402.HEADER_RESPONSE))
    tx = settled["transaction"]
    receipt = _rpc(rpc, "eth_getTransactionReceipt", [tx])
    buyer_after, seller_after = balance(buyer), balance(seller)
    retry, retry_body, _ = _http_get(url, headers)
    retry_delta = balance(seller) - seller_after
    if not (
        settled["success"] and _tx_ok(receipt) and receipt["to"].lower() == USDC.lower()
        and buyer_after - buyer_before == -X402_AMOUNT
        and seller_after - seller_before == X402_AMOUNT
        and retry == 402 and not json.loads(retry_body)
        and balance(buyer) == buyer_after and retry_delta == 0
    ):
        raise RuntimeError("The payment or repeat-authorization check did not match the measured balances.")
    return {
        "mode": "local Base Sepolia fork",
        "network": settled["network"],
        "fork_block": BLOCK,
        "fork_block_hash": BLOCK_HASH,
        "token": USDC,
        "http": {"challenge": challenge, "paid": paid, "retry": retry},
        "buyer_delta_raw": buyer_after - buyer_before,
        "seller_delta_raw": seller_after - seller_before,
        "retry_delta_raw": retry_delta,
        "local_settlement_tx": tx,
        "remote_writes": counter.count,
        "quote": json.loads(body),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("PASS · Base Sepolia fork: 402 → paid quote, 0.05 test USDC settled, repeat authorization refused.")
