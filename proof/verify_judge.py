"""Verify retained forecast inputs and saved fork receipts offline."""
import csv
import datetime as dt
from hashlib import sha256

from collateral_card.rule import replay_weekends
from verify import PROOF, load_judge, read, require_equal, verify_fork, verify_recorded
from weekend_forecast import backtest


def key(row):
    return row["symbol"], row["weekend_friday"]


def verify_forecast(judge, inputs):
    result = backtest.run()
    summary = result["summary"]
    published = judge["rows"]
    require_equal(len(result["rows"]), 24, "Forecast row count")
    require_equal(len(published), 24, "Published row count")

    with (PROOF / "backtest-observations.csv").open(newline="", encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    selected = {key(row): row for row in records}
    require_equal(len(records), 24, "Provenance table length")
    require_equal(set(selected), {key(row) for row in result["rows"]}, "Provenance rows")
    oracles = {symbol: backtest.load(f"oracle-{symbol}.json")["rows"]
               for symbol in backtest.SYMBOLS}
    pools = {(symbol, pool): backtest.load(f"pool-{symbol}-{pool}.json")["rows"]
             for symbol in backtest.SYMBOLS for pool in ("main", "old")}
    charts = 0
    for row, original in zip(result["rows"], published):
        symbol, friday = key(row)
        label = f"{symbol} {friday}"
        for field, value in row.items():
            require_equal(value, original[field], f"{label} {field}")
        observation = selected[symbol, friday]
        require_equal(observation["pool"], row["pool"], f"{label} selected pool")
        friday_utc = dt.datetime.fromisoformat(friday).replace(tzinfo=dt.timezone.utc)
        saturday = int((friday_utc + dt.timedelta(days=1)).timestamp())
        monday = int((friday_utc + dt.timedelta(days=3)).timestamp())
        oracle = oracles[symbol]
        frozen = max((r for r in oracle if r["updatedAt"] < saturday),
                     key=lambda r: r["updatedAt"])
        reopen = min((r for r in oracle if r["updatedAt"] >= monday),
                     key=lambda r: r["updatedAt"])
        for name, reading in (("frozen", frozen), ("reopen", reopen)):
            require_equal(reading["phase"], 2, f"{label} {name} oracle phase")
            require_equal(reading["round"], int(observation[f"{name}_round"]), f"{label} {name} round")
            require_equal(reading["updatedAt"], int(observation[f"{name}_updated_at_unix"]),
                          f"{label} {name} timestamp")
            require_equal(reading["answer"], float(observation[f"{name}_usd"]), f"{label} {name} price")
        require_equal(reopen["round"], frozen["round"] + 1, f"{label} consecutive oracle rounds")
        require_equal(row["oracle_updates_during_weekend"], 0, f"{label} weekend updates")

        bars = pools[symbol, row["pool"]]
        chart = [bar for bar in bars if saturday <= bar[0] < reopen["updatedAt"]]
        require_equal([[bar[0], round(bar[4], 4)] for bar in chart], original["dex_closes"],
                      f"{label} chart points")
        candle = max((bar for bar in chart if bar[0] < monday), key=lambda bar: bar[0])
        require_equal(candle[0] + 3600, monday, f"{label} forecast candle close time")
        require_equal(candle[0], int(observation["sunday_candle_open_unix"]), f"{label} candle timestamp")
        require_equal(candle[4], float(observation["sunday_close_usd"]), f"{label} candle close price")
        charts += len(chart)
    require_equal({name: summary[name] for name in judge["summary"]},
                  judge["summary"], "Published forecast summary")
    require_equal(summary["band_pts"], inputs["band_pts"], "In-sample error band")

    rule = replay_weekends(result["rows"], inputs["target_starting_health"],
                           summary["band_pts"], inputs["collateral_factor"])
    count_fields = ("repaid_weekends", "saved", "unneeded_repays")
    require_equal(tuple(rule[name] for name in count_fields), (11, 1, 10), "Published rule results")
    weekends = len({row["weekend_friday"] for row in result["rows"]})
    print("PASS  Saved Base market data and forecast")
    print(f"      {summary['n']} token-weekends across {weekends} calendar weekends, {charts:,} chart points")
    print(f"      Direction {summary['sign_agree']}/{summary['n']}. In-sample error band {summary['band_pts']:.2f} points.")
    sample, = (row for row in result["rows"] if key(row) == (inputs["symbol"], inputs["weekend_friday"]))
    require_equal(sample["predicted_pct"], inputs["predicted_pct"], "Replay sample forecast")
    print(f"      {sample['symbol']} {sample['weekend_friday']}: predicted {sample['predicted_pct']:+.2f}%.")
    print(f"      At health {inputs['target_starting_health']:.4f}: {rule['repaid_weekends']} repayments, "
          f"{rule['saved']} save, {rule['unneeded_repays']} false alarms.")


def verify_replay(judge, inputs):
    recorded = read(PROOF / "recorded-comparison.json")
    pinned = read(PROOF / "pinned-comparison.json")
    verify_recorded(judge, inputs, recorded)
    verify_fork(pinned, inputs, recorded)
    print(f"PASS  Saved NVDAc loan replay receipts at Base block {inputs['fork_block']:,}")
    for scenario, title in (("paid", "Simulated payments"), ("control", "Income removed")):
        receipt = pinned[scenario]
        if not 0 <= receipt["repaid_raw"] <= receipt["income_raw"]:
            raise SystemExit(f"{scenario}: repayment exceeds simulated proceeds")
        require_equal(receipt["collateral_after_raw"], recorded[scenario]["collateral_after_raw"],
                      f"{scenario} remaining collateral")
        print(f"      {title}: {receipt['repaid_raw'] / 1e6:.2f} USDC repaid, "
              f"health {receipt['hf_after_reopen']:.4f}, {receipt['liquidation_attempt']}.")
    print("      Saved receipt verification. The original demo endpoint returned an acknowledgment.")


def verify_pins():
    # A changed observation should fail the calculation above with a named row.
    # Pins also catch edits to unused portions of a retained snapshot.
    for line in (PROOF / "INPUT-SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        require_equal(sha256((PROOF / name).read_bytes()).hexdigest(), expected, f"Pinned file {name}")



def main():
    judge = load_judge()
    inputs = read(PROOF / "inputs.json")
    verify_forecast(judge, inputs)
    print()
    verify_replay(judge, inputs)
    verify_pins()
    print("PASS  Bundled evidence matches its saved checksums.")


if __name__ == "__main__":
    main()
