"""Dated price comparisons from the exhibit's verified Base observations."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

OBSERVATIONS = Path(__file__).resolve().parents[1] / "backtest-observations.csv"
DEMO_REQUEST = ("NVDAc", "2026-11-06", "2026-11-09T00:05:00Z")


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def weekend_quote(stock, weekend, as_of_utc):
    at = datetime.fromisoformat(as_of_utc.replace("Z", "+00:00"))
    if at.tzinfo is None or at.utcoffset() != timezone.utc.utcoffset(at):
        raise ValueError("Provide a UTC timestamp.")
    with OBSERVATIONS.open(newline="", encoding="utf-8") as source:
        row = next(
            (row for row in csv.DictReader(source)
             if (row["symbol"], row["weekend_friday"]) == (stock, weekend)),
            None,
        )
    if row is None:
        raise ValueError("No recorded Base observation for this stock and weekend.")
    lender_at = int(row["frozen_updated_at_unix"])
    market_at = int(row["sunday_candle_open_unix"]) + 3600
    reopen_at = int(row["reopen_updated_at_unix"])
    if not lender_at <= market_at <= at.timestamp() < reopen_at:
        raise ValueError("The saved candle is open or the lending feed has reopened.")
    lender_price = Decimal(row["frozen_usd"])
    market_price = Decimal(row["sunday_close_usd"])
    gap = ((market_price / lender_price - 1) * 100).quantize(Decimal(".01"))
    return {
        "mode": "historical replay",
        "network": "Base",
        "stock": stock,
        "weekend_friday": weekend,
        "as_of_utc": at.isoformat().replace("+00:00", "Z"),
        "lending_price_usd": str(lender_price),
        "lending_price_at_utc": _utc(lender_at),
        "pool_close_usd": str(market_price),
        "pool_close_at_utc": _utc(market_at),
        "pool_minus_lending_percent": str(gap),
        "source": {"lending_round": row["frozen_round"], "pool_series": row["pool"]},
    }
