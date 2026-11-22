"""Verify the published comparison and its input row offline."""
import argparse
import json
from pathlib import Path

PROOF = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require_equal(actual, expected, label):
    if actual != expected:
        raise SystemExit(f"{label}: expected {expected!r}, got {actual!r}")


def load_judge():
    bundled = (PROOF.parent / "data.js").read_text(encoding="utf-8").strip()
    prefix = "window.JUDGE_DATA = "
    if not bundled.startswith(prefix) or not bundled.endswith(";"):
        raise SystemExit("The judge bundle does not have the expected JSON wrapper.")
    return json.loads(bundled[len(prefix):-1])


def verify_recorded(judge, inputs, recorded):
    row, = (row for row in judge["rows"] if
            (row["symbol"], row["weekend_friday"]) == (inputs["symbol"], inputs["weekend_friday"]))
    for field in ("frozen", "reopen", "predicted_pct"):
        require_equal(row[field], inputs[field], field)
    for field, bundled_field in (("band_pts", "band_pts"), ("collateral_factor", "cf"),
                                 ("target_starting_health", "start_hf_demo")):
        require_equal(judge[bundled_field], inputs[field], field)

    for scenario, name in (("paid", "funded"), ("control", "no_income")):
        receipt = judge["earned"][name]
        for field, expected in recorded[scenario].items():
            require_equal(receipt[field], expected, f"{scenario} recorded {field}")
        require_equal(receipt["sales"], inputs[f"{scenario}_sales"], f"{scenario} sales")
        require_equal(receipt["price_raw"], inputs["quote_price_raw"], f"{scenario} quote price")
        require_equal(receipt["collateral_before_raw"], inputs["starting_collateral_raw"],
                      f"{scenario} starting collateral")
        require_equal(receipt["income_raw"], receipt["sales"] * receipt["price_raw"], f"{scenario} income")
        require_equal(receipt["agent_usdc_after_ringfence_raw"], 0, f"{scenario} starting wallet USDC")



def verify_fork(receipts, inputs, recorded):
    for scenario in ("paid", "control"):
        actual = receipts[scenario]
        original = recorded[scenario]
        for field in ("fork_block", "fork_block_hash"):
            require_equal(actual[field], inputs[field], f"{scenario} fork {field}")
        for field in ("weekend", "token", "chain_id", "frozen_price", "reopen_price",
                      "sales", "price_raw", "income_raw", "agent_usdc_after_ringfence_raw",
                      "repay_tx_status", "liquidation_attempt", "remote_writes",
                      "collateral_before_raw"):
            require_equal(actual[field], original[field], f"{scenario} fork {field}")
        require_equal(f"{actual['repaid_raw'] / 1e6:.2f}",
                      f"{original['repaid_raw'] / 1e6:.2f}", f"{scenario} rounded repayment")
        require_equal(f"{actual['hf_after_reopen']:.4f}",
                      f"{original['hf_after_reopen']:.4f}", f"{scenario} rounded health")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fork-results", nargs=2, type=Path, metavar=("PAID", "CONTROL"))
    args = parser.parse_args()
    inputs = read(PROOF / "inputs.json")
    recorded = read(PROOF / "recorded-comparison.json")
    verify_recorded(load_judge(), inputs, recorded)
    if args.fork_results:
        receipts = dict(zip(("paid", "control"), map(read, args.fork_results)))
        verify_fork(receipts, inputs, recorded)
        print("Pinned fork outputs match the recorded comparison at display precision.")
    print("Recorded inputs and comparison match the published judge bundle.")


if __name__ == "__main__":
    main()
