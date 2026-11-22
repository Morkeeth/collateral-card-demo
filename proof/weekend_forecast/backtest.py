"""Backtest: does the last Sunday DEX close predict the Sunday-night oracle jump?

Ported from HACK-BASE gaps.py (20 Nov 2026). Computed from the raw files, not from a derived table:
- fixtures/oracle-*.json: every Chainlink round of the feed (getRoundData via base-rpc.publicnode.com).
- fixtures/pool-*-{main,old}.json: GeckoTerminal hourly OHLCV, rows [ts, open, high, low, close, volume].

Definitions (the same ones the live forecast and the Monday scorer use):
- frozen = last oracle answer with updatedAt before Saturday 00:00 UTC.
- reopen = first oracle answer with updatedAt at or after Monday 00:00 UTC.
- jump = 100 * (reopen - frozen) / frozen.
- predicted = 100 * (last hourly DEX close of a bar that opens before Monday 00:00 UTC - frozen) / frozen.
- miss = |predicted - jump|, in percentage points.
"""
import datetime as dt
import json
import math
import os

UTC = dt.timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(os.path.dirname(HERE), "fixtures")
SYMBOLS = ["NVDAc", "TSLAc", "AAPLc"]
# Eight weekends, Fridays 25 Sep to 13 Nov 2026 (gaps.py FRIDAYS).
FRIDAYS = [dt.datetime(2026, 11, 13, tzinfo=UTC) - dt.timedelta(weeks=k) for k in range(8)]
MAIN_START = 1792634400  # first bar of the main pools, 22 Oct 2026 (gaps.py)
BAND_QUANTILE = 0.8


def load(name, fixtures=FIXTURES):
    with open(os.path.join(fixtures, name)) as f:
        return json.load(f)


def weekend_row(sym, fri, orc, main, old):
    sat = int((fri + dt.timedelta(days=1)).timestamp())
    mon = int((fri + dt.timedelta(days=3)).timestamp())
    before = [r for r in orc if r["updatedAt"] < sat]
    after = [r for r in orc if r["updatedAt"] >= mon]
    during = [r for r in orc if sat <= r["updatedAt"] < mon]
    if not before or not after:
        return None
    frozen, reopen = before[-1], after[0]
    pool, pname = (main, "main") if sat >= MAIN_START + 86400 else (old, "old")
    bars = [b for b in pool if sat <= b[0] < reopen["updatedAt"]]
    sunday = [b for b in bars if b[0] < mon]
    if not bars or not sunday:
        return None
    f = frozen["answer"]
    jump = 100 * (reopen["answer"] - f) / f
    pred = 100 * (sunday[-1][4] - f) / f
    return {"symbol": sym, "weekend_friday": fri.date().isoformat(), "pool": pname,
            "frozen": round(f, 4), "reopen": round(reopen["answer"], 4),
            "reopen_at_utc": dt.datetime.fromtimestamp(reopen["updatedAt"], UTC).isoformat(),
            "oracle_updates_during_weekend": len(during),
            "jump_pct": round(jump, 2), "predicted_pct": round(pred, 2),
            "miss_pts": round(abs(pred - jump), 2),
            "sign_agree": (pred > 0) == (jump > 0)}


def quantile(xs, q):
    """Nearest-rank quantile: the smallest value with at least q of the sample at or below it."""
    s = sorted(xs)
    k = max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))
    return s[k]


def run(fixtures=FIXTURES):
    rows = []
    for sym in SYMBOLS:
        orc = load(f"oracle-{sym}.json", fixtures)["rows"]
        main = load(f"pool-{sym}-main.json", fixtures)["rows"]
        old = load(f"pool-{sym}-old.json", fixtures)["rows"]
        for fri in FRIDAYS:
            r = weekend_row(sym, fri, orc, main, old)
            if r:
                rows.append(r)
    misses = [r["miss_pts"] for r in rows]
    summary = {
        "n": len(rows),
        "sign_agree": sum(r["sign_agree"] for r in rows),
        "mean_abs_miss_pts": round(sum(misses) / len(misses), 2),
        "max_abs_miss_pts": round(max(misses), 2),
        "band_quantile": BAND_QUANTILE,
        "band_pts": round(quantile(misses, BAND_QUANTILE), 2),
        "weekends_with_oracle_updates": sum(1 for r in rows if r["oracle_updates_during_weekend"]),
        "per_symbol": {},
    }
    for sym in SYMBOLS:
        m = [r["miss_pts"] for r in rows if r["symbol"] == sym]
        if m:
            summary["per_symbol"][sym] = {"n": len(m), "mean_abs_miss_pts": round(sum(m) / len(m), 2),
                                          "max_abs_miss_pts": round(max(m), 2)}
    return {"method": __doc__.strip().splitlines()[0], "summary": summary, "rows": rows}
