"""Local fork: repay a Mag7 loan from x402 payment income after ring-fencing the borrow."""
from __future__ import annotations

import json
import os
import subprocess
import time

from collateral_card.guard import require_local
from collateral_card import rule
from collateral_card.demo import (
    CF,
    CHAIN_ID,
    DEX_POOL,
    FEED,
    FORK_URL_READ,
    HUB,
    INPUTS,
    NVDAC,
    RESERVE_USDC,
    SPOKE,
    START_HF,
    SUPPLY_RAW,
    USDC,
    _RemoteWriteCounter,
    _accounts,
    _build_standins,
    _call_uint,
    _cast_send,
    _fixture_row,
    _free_port,
    _pinned_block,
    _liquidate,
    _open_position,
    _read_hub_nvdac_balance,
    _rpc,
    _set_balance,
    _set_code,
    _set_feed,
    _start_x402_server,
    _stop_impersonate,
    _impersonate,
    _supplied,
    _tx_ok,
    _user_account,
    _x402_flow,
)
from collateral_card import x402 as x402_mod


def _total_debt(rpc: str, user: str) -> int:
    return _call_uint(rpc, SPOKE, "getUserTotalDebt(uint256,address)(uint256)", str(RESERVE_USDC), user)


def _fund_usdc_from_pool(rpc: str, counter: _RemoteWriteCounter, *allocations: tuple[str, int]):
    """Transfer USDC from the stand-in DEX pool; each (recipient, max_raw), one impersonation."""
    _impersonate(rpc, DEX_POOL, counter)
    _set_balance(rpc, DEX_POOL, 10**18, counter)
    pool_left = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", DEX_POOL)
    for recipient, max_raw in allocations:
        if max_raw <= 0:
            continue
        fund = min(pool_left, max_raw)
        if fund <= 0:
            continue
        r = _cast_send(rpc, DEX_POOL, USDC, "transfer(address,uint256)", recipient, str(fund), counter=counter)
        if not _tx_ok(r):
            raise RuntimeError(f"fund from pool failed: {r}")
        pool_left -= fund
    _stop_impersonate(rpc, DEX_POOL, counter)


def run(
    weekend: str,
    token: str,
    out_dir: str,
    sales: int,
    price_raw: int,
) -> dict:
    if token != "NVDAc":
        raise ValueError("earned currently wired for NVDAc only")
    if sales < 0:
        raise ValueError("sales must be non-negative")

    row, band_pts = _fixture_row(weekend, token)
    frozen = row["frozen"]
    reopen = row["reopen"]
    borrow_raw = int(2 * frozen * CF / START_HF * 1e6)

    counter = _RemoteWriteCounter()
    standin_bytecodes = _build_standins()

    anvil_proc = None
    server = None
    try:
        port = _free_port()
        block = _pinned_block()
        hub_bal = _read_hub_nvdac_balance(block)
        anvil_proc = subprocess.Popen(
            [
                "anvil",
                "--fork-url", FORK_URL_READ,
                "--fork-block-number", str(block),
                "--host", "127.0.0.1",
                "--port", str(port),
                "--silent",
                "--hardfork", "jovian",
                "--optimism",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        rpc = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                _rpc(rpc, "eth_chainId", [])
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("anvil did not start")
        require_local(rpc)
        accounts = _accounts(rpc)
        deployer, agent, liquidator, buyer, spend_sink = (
            accounts[0], accounts[1], accounts[2], accounts[3], accounts[4],
        )

        for acct in (deployer, agent, liquidator, buyer, spend_sink):
            _set_code(rpc, acct, "0x", counter)

        _set_code(rpc, NVDAC, standin_bytecodes["MintableERC20"], counter)
        _set_code(rpc, FEED, standin_bytecodes["SettableFeed"], counter)
        for to, amount in ((HUB, hub_bal), (agent, SUPPLY_RAW)):
            r = _cast_send(rpc, deployer, NVDAC, "mint(address,uint256)", to, str(amount), counter=counter)
            if not _tx_ok(r):
                raise RuntimeError(f"mint failed: {r}")

        _set_feed(rpc, frozen, deployer, counter)

        _open_position(rpc, agent, borrow_raw, counter)

        agent_usdc = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", agent)
        if agent_usdc > 0:
            r = _cast_send(
                rpc, agent, USDC, "transfer(address,uint256)", spend_sink, str(agent_usdc), counter=counter,
            )
            if not _tx_ok(r):
                raise RuntimeError(f"ring-fence transfer failed: {r}")

        agent_usdc_after_ringfence_raw = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", agent)
        if agent_usdc_after_ringfence_raw != 0:
            raise RuntimeError(
                f"ring-fence failed: agent USDC balance {agent_usdc_after_ringfence_raw}, expected 0"
            )

        buyer_cap = sales * price_raw if sales else 0
        _fund_usdc_from_pool(
            rpc, counter,
            (buyer, buyer_cap),
            (liquidator, 1_000_000_000_000),
        )

        terms = x402_mod.requirements(pay_to=agent, amount_raw=price_raw)
        server, server_base = _start_x402_server(rpc, agent, terms, counter)

        agent_before_sales = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", agent)
        buyer_before = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", buyer)

        for _ in range(sales):
            flow = _x402_flow(rpc, server_base, buyer, agent)
            if flow["paid_status"] != 200 or not (flow.get("settlement") or {}).get("success"):
                raise RuntimeError(f"x402 sale failed: {flow}")

        agent_usdc_after_sales_raw = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", agent)
        buyer_after = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", buyer)
        income_raw = agent_usdc_after_sales_raw - agent_before_sales
        buyer_usdc_delta_raw = buyer_after - buyer_before

        debt_before_repay_raw = _total_debt(rpc, agent)

        collateral_usd = 2 * frozen
        debt_usd = debt_before_repay_raw / 1e6
        wallet_raw = agent_usdc_after_sales_raw
        decision = rule.decide(
            collateral_usd, debt_usd, CF, row["predicted_pct"], band_pts, wallet_usd=wallet_raw / 1e6,
        )

        repay_tx_status = None
        repaid_raw = 0
        if decision["action"] == "REPAY":
            repay_candidate = int(decision["repay_usd"] * 1e6)
            repay_raw = min(repay_candidate, wallet_raw)
            if repay_raw > 0:
                r = _cast_send(
                    rpc, agent, SPOKE, "repay(uint256,uint256,address)",
                    str(RESERVE_USDC), str(repay_raw), agent, counter=counter,
                )
                repay_tx_status = 1 if _tx_ok(r) else 0
                if repay_tx_status == 1:
                    repaid_raw = repay_raw
                else:
                    raise RuntimeError(f"repay failed: {r}")

        debt_after_repay_raw = _total_debt(rpc, agent)
        agent_usdc_after_repay_raw = _call_uint(rpc, USDC, "balanceOf(address)(uint256)", agent)

        coll_before = _supplied(rpc, agent)
        _set_feed(rpc, reopen, deployer, counter)
        hf_after_reopen = _user_account(rpc, agent)["hf"]

        r = _cast_send(rpc, liquidator, USDC, "approve(address,uint256)", SPOKE, str((1 << 256) - 1), counter=counter)
        if not _tx_ok(r):
            raise RuntimeError(f"liquidator approve failed: {r}")
        liquidation_attempt = _liquidate(rpc, liquidator, agent, counter)
        coll_after = _supplied(rpc, agent)

        receipt = {
            "mode": "mainnet fork, replayed reopen, repay from x402 income",
            "fork_block": block,
            "fork_block_hash": INPUTS["fork_block_hash"],
            "chain_id": CHAIN_ID,
            "stand_ins": [
                "MintableERC20",
                "SettableFeed",
                "stand-in quote buyer",
                "stand-in loan spend",
            ],
            "weekend": weekend,
            "token": token,
            "frozen_price": frozen,
            "reopen_price": reopen,
            "sales": sales,
            "price_raw": price_raw,
            "remote_writes": counter.count,
            "agent_usdc_after_ringfence_raw": agent_usdc_after_ringfence_raw,
            "agent_usdc_after_sales_raw": agent_usdc_after_sales_raw,
            "income_raw": income_raw,
            "buyer_usdc_delta_raw": buyer_usdc_delta_raw,
            "debt_before_repay_raw": debt_before_repay_raw,
            "debt_after_repay_raw": debt_after_repay_raw,
            "repaid_raw": repaid_raw,
            "agent_usdc_after_repay_raw": agent_usdc_after_repay_raw,
            "decision": decision,
            "repay_tx_status": repay_tx_status,
            "hf_after_reopen": hf_after_reopen,
            "liquidation_attempt": liquidation_attempt,
            "collateral_before_raw": coll_before,
            "collateral_after_raw": coll_after,
        }

        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "earned-receipt.json")
        with open(path, "w") as f:
            json.dump(receipt, f, indent=2)
        return receipt
    finally:
        if server is not None:
            server.shutdown()
        if anvil_proc is not None:
            anvil_proc.terminate()
            try:
                anvil_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                anvil_proc.kill()