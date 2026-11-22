"""Run one of the published scenarios against a disposable local Base fork."""
import argparse
from pathlib import Path

from collateral_card.demo import INPUTS
from collateral_card.earned import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("paid", "control"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    receipt = run(
        INPUTS["weekend_friday"],
        INPUTS["symbol"],
        str(args.out),
        INPUTS[f"{args.scenario}_sales"],
        INPUTS["quote_price_raw"],
    )
    print(f"{args.scenario}: ${receipt['repaid_raw'] / 1e6:.2f} repaid, "
          f"health {receipt['hf_after_reopen']:.4f}, "
          f"liquidation {receipt['liquidation_attempt']}, "
          f"{receipt['remote_writes']} remote writes")


if __name__ == "__main__":
    main()
