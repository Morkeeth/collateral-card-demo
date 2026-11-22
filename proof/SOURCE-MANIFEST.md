# Weekend backtest sources

The backtest uses 24 token-weekends for NVDAc, TSLAc and AAPLc, across eight Fridays from 25 September through 13 November 2026. The original collection report dated 20 November 2026 records the oracle reads at 18:06 UTC and DEX reads at 18:09 UTC. [Selected observations](backtest-observations.csv) gives the two oracle rounds and the exact DEX close used in each estimate. Unix times are UTC seconds. Read the round IDs as decimal strings or integers with at least 80 bits of precision.

## DEX candles

The retained collector, `fetch_pool.py`, requested GeckoTerminal's public Base pool route `/api/v2/networks/base/pools/{pool}/ohlcv/hour` with `aggregate=1&limit=1000&currency=usd&token=base`. It read up to two pages, using the earliest candle's timestamp as the next `before_timestamp`, and sorted and deduplicated candles by opening timestamp. Each candle contains `[open_time, open, high, low, close, volume]`.

| Token | Older pool, 25 Sep–16 Oct Fridays | Main pool, 23 Oct–13 Nov Fridays |
| --- | --- | --- |
| NVDAc | `0x853f5f1b92b16714fe6cda67caad0856b83c7ab9` | `0xf668e21993f0acd7ab00bb1cfbaed0df28a3c8ec` |
| TSLAc | `0x469337fdcc5e8f38e2e4b670b04f57865d13a7bb` | `0x7a33000372f3f028f074182ccb9d16cbeefbf920` |
| AAPLc | `0xa3b1e3f9747065e2073722ff4c9027d3ea4994f0` | `0xf5fcb9cdafce67d50afef298f88e709d2b946ba6` |

The saved older pools start at 29 Aug 12:00 (NVDAc), 3 Sep 20:00 (TSLAc) and 29 Aug 10:00 (AAPLc). All three main pools start at 22 Oct 02:00. All six end at 20 Nov 18:00. These are candle opening times. Each forecast uses the last hourly candle opening before Monday 00:00 UTC within the Saturday-to-Monday window. That candle closes at Monday 00:00 UTC for all 24 rows. The chart additionally plots full candle closes at their opening times. Its final plotted candle opens before the oracle reopens and closes afterward.

## Oracle rounds

The retained collector, `oracle_rounds.py`, used `https://base-rpc.publicnode.com` on Base (8453), calling `latestRound()` and batching `getRoundData(uint80)` with `eth_call` at tag `latest`. It decoded signed answers with eight decimals and saved the proxy round ID, phase, answer and `updatedAt`. The backtest takes the last saved round before Saturday 00:00 UTC and the first saved round at or after Monday 00:00 UTC. There are zero saved rounds inside that weekend window in all 24 cases. All 24 selected pairs are consecutive within phase 2.

| Token | Chainlink proxy | Saved rounds | Last saved `updatedAt` (20 Nov UTC) |
| --- | --- | ---: | --- |
| NVDAc | `0x04689a41629776563E6822F76f2e57D148d28513` | 1,696 | 17:58:58 |
| TSLAc | `0xFaf869185383a24F8cb00e27BdA6b63B9905DCb4` | 1,693 | 17:02:37 |
| AAPLc | `0x787f13dEa48Db0897CbCDD985de77809D837F988` | 669 | 17:19:20 |

Each saved series begins on 3 August 2026. The retained `gaps.py` export and the offline forecaster agree on the selected reopen and percentage moves. The page builder derives the published rows, chart points and band from the saved files and embeds the fork receipts separately.

## Offline reproduction

From the repository root with Python 3.10 or later, run:

```sh
python3 -B proof/verify_judge.py
```

The [retained files](fixtures/) contain six normalized pool snapshots and three oracle snapshots. The verifier runs the original [historic backtest calculation](weekend_forecast/backtest.py) and compares each derived row and chart with the bundled demo. It confirms the selected rounds and candle for each CSV row. [Checksums](INPUT-SHA256SUMS) pin the bundled copy of these inputs, the demo data and the replay receipts. The 0.71 percentage-point band is the in-sample nearest-rank 80th percentile of the rounded absolute errors.

## Optional source check for the 6 November NVDAc replay

These two small network reads use fixed public HTTPS routes, a clean curl environment, no curl config and no redirects. They need no account, API credential or wallet. The DEX check selects the Sunday candle that opened at 8 Nov 23:00 UTC and closed at 9 Nov 00:00 UTC.

```sh
set -o pipefail
env -i PATH=/usr/bin:/bin /usr/bin/curl -q -fsS --proto '=https' \
  --connect-timeout 8 --max-time 20 --max-filesize 100000 \
  -A curl/8.7.1 -H 'Accept: application/json' \
  'https://api.geckoterminal.com/api/v2/networks/base/pools/0xf668e21993f0acd7ab00bb1cfbaed0df28a3c8ec/ohlcv/hour?aggregate=1&limit=2&currency=usd&token=base&before_timestamp=1794182400' |
  python3 -I -c 'import json, sys
rows = json.load(sys.stdin)["data"]["attributes"]["ohlcv_list"]
observed = [(r[0], r[4]) for r in rows if r[0] == 1794178800]
assert observed == [(1794178800, 178.46556282635999)], observed
print(observed)'
```

The oracle check reads the exact saved consecutive rounds. It prints the returned round ID, raw USD answer and `updatedAt` for each. The times are 6 Nov 21:39:16 UTC and 9 Nov 01:00:33 UTC.

```sh
set -o pipefail
python3 -I - <<'PY' |
import json
feed = "0x04689a41629776563E6822F76f2e57D148d28513"
rounds = (36893488147419104163, 36893488147419104164)
print(json.dumps([
    {"jsonrpc": "2.0", "id": i, "method": "eth_call",
     "params": [{"to": feed, "data": f"0x9a6fc8f5{r:064x}"}, "latest"]}
    for i, r in enumerate(rounds, 1)
]))
PY
  env -i PATH=/usr/bin:/bin /usr/bin/curl -q -fsS --proto '=https' \
    --connect-timeout 8 --max-time 20 --max-filesize 100000 \
    -A curl/8.7.1 -H 'Content-Type: application/json' --data-binary @- \
    'https://base-rpc.publicnode.com' |
  python3 -I -c 'import json, sys
observed = []
for item in sorted(json.load(sys.stdin), key=lambda r: r["id"]):
    data = item["result"][2:]
    words = [int(data[i:i+64], 16) for i in range(0, len(data), 64)]
    observed.append((words[0], words[1], words[3]))
assert observed == [(36893488147419104163, 18796606001, 1794001156),
                    (36893488147419104164, 18303263669, 1794186033)], observed
for row in observed:
    print(*row)'
```

## Collection evidence limits

The retained files are normalized collector outputs. The original OHLCV pages, exact per-request times, candle publication times, candle-to-swap mappings and source block ranges were not retained. The oracle run did not pin a block, and its original RPC envelopes, response block hashes and per-round block or transaction IDs were not retained. Round IDs, candle opening timestamps and normalized values are available for the targeted reads above. Provider rate limits and candle revisions can affect fresh reads. A fresh read checks today's answer for the selected observation, and the offline command checks the saved data used in the demo.

Block `60423882` and its hash in [inputs.json](inputs.json) identify the pinned fork rerun. The original comparison receipt did not preserve its fork height. Neither fork receipt supplies any backtest collection block or a historical repayment timestamp.
