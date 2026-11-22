# Collateral Card

A stock-backed loan can look healthy while its lending oracle still shows Friday's price. Collateral Card watches the weekend gap and tests whether simulated x402 payment proceeds can reduce debt before the oracle updates.

## Verify offline

From this folder, run the complete offline check with Python 3.10 or later.

```sh
python3 -B proof/verify_judge.py
```

The command rebuilds the forecast from the retained oracle rounds and DEX candles, verifies the recorded rule outcomes, and checks the two saved loan replay receipts against the recorded comparison. The [source manifest](proof/SOURCE-MANIFEST.md) explains the collection and the in-sample error band. The [receipt guide](proof/README.md) explains the separate fork evidence.

**Open the [public demo](https://morkeeth.github.io/collateral-card-demo/).** The demo requires no wallet or account. Built for Base Stocks Maxxing, Agentic Stock Finance track.

## Simulated payment replay

These saved receipts replay the 6 November 2026 NVDAc weekend on a local Base mainnet fork with stand-in collateral and one simulated buyer. The buyer paid a demo endpoint that returned an acknowledgment.

| | With simulated x402 payments | Income removed |
| --- | ---: | ---: |
| Simulated x402 payments | 518 | 0 |
| Income | 25.90 USDC | 0 USDC |
| Debt repaid | 25.87 USDC | 0 USDC |
| Health after the oracle update | 1.0851 | 0.9780 |
| Liquidation attempt | Refused | Succeeded |

## Original demo components · 20–22 November 2026

- A repayment rule that compares the market price with a frozen lending price ([rule.py](proof/collateral_card/rule.py)).
- An x402 v2 payment flow for a demo endpoint ([x402.py](proof/collateral_card/x402.py)).
- A fork replay that repays an Aave Mag7 loan from simulated x402 payment proceeds ([earned.py](proof/collateral_card/earned.py)).
- A guard that refuses any write path outside local loopback ([guard.py](proof/collateral_card/guard.py)).
- The interactive judge page in this repository.

To rerun both loans on a local fork, follow [the reproduction steps](proof/README.md). The rerun needs Foundry and native `solc` 0.8.20. It needs no wallet or API key, and it makes no mainnet transactions.

## Limits

- The results come from a local fork with a replayed oracle update. No real loan has been taken.
- The Aave and USDC contracts are the fork's. The collateral token and price feed are stand-ins.
- All 518 payments came from one simulated buyer. The demo endpoint, at the route `/quote`, returns the acknowledgment `{"ok":true}` and delivers no forecast. Some code and receipt labels still use the word "quote". Customer demand and repayment economics are untested.
- The x402 server and facilitator run locally.
- At the replayed starting health, the rule repaid on 11 of 24 token-weekends (3 tokens over 8 calendar weekends). One repayment was needed and 10 were false alarms.
- The historic backtest calculation and its normalized snapshots are bundled here. The live collector and forecaster are outside the bundle. The local fork block identifies the receipt rerun. The original source request envelopes and collection blocks are unavailable.
