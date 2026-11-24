# Stock Desk for agents

An agent that keeps its savings in tokenized stocks on Base, and borrows USDC against them to pay for its work, asks the desk before every spend. The desk shows positions, exposure per stock and health in two views: the frozen lending price the lender uses over the weekend, and the closed Base pool price minus the forecast error band. It then allows the spend, asks for a repayment first, or refuses. It never buys or sells stock.

## Try the desk

```sh
python3 -B proof/run_desk.py                 # print the desk receipt for the saved 6 November weekend
python3 -B proof/run_desk.py --serve 8851    # GET /desk and /desk/spend?usd=25 on loopback
```

On the saved weekend the lender view shows health 1.413 and the weekend view 1.358 against an owner floor of 1.30. A 25 USDC spend passes on Friday's price and needs an 8.69 USDC repayment first on the weekend price. When the feed reopened the floor held either way, so that repayment was caution, not a rescue. The book is a demo book, not a real wallet, and the prices are historical replays. The [desk receipt](demo/desk.json) is the captured run and [desk.py](proof/collateral_card/desk.py) is the code. Tests: `cd tests && python3 -B -m unittest test_desk`.

The loan rule underneath is Collateral Card, described below.

# Collateral Card

A stock-backed loan can look healthy while its lending oracle still shows Friday's price. Collateral Card watches the weekend gap and tests whether simulated x402 payment proceeds can reduce debt before the oracle updates.

## Verify offline

From this folder, run the complete offline check with Python 3.10 or later.

```sh
python3 -B proof/verify_judge.py
```

The command rebuilds the forecast from the retained oracle rounds and DEX candles, verifies the recorded rule outcomes, and checks the two saved loan replay receipts against the recorded comparison. The [source manifest](proof/SOURCE-MANIFEST.md) explains the collection and the in-sample error band. The [receipt guide](proof/README.md) explains the separate fork evidence.

**Open the [public demo](https://morkeeth.github.io/collateral-card-demo/).** The demo requires no wallet or account. Built for Base Stocks Maxxing, Agentic Stock Finance track.

## Try the paid price check

A buyer gets the last frozen NVDAc Aave price and the closed Base pool candle with their UTC timestamps and percentage gap. To reproduce the HTTP challenge, Circle test USDC settlement and repeat-payment refusal on a disposable Base Sepolia fork, install Foundry with `anvil` and `cast` on your PATH and run:

```sh
python3 -B proof/run_sepolia.py --out /tmp/collateral-paid-quote.json
```

The fork uses public read-only Base Sepolia RPC and local dev accounts. The [browser receipt](demo/paid-quote.json) is a captured run. The prices are historical Base mainnet observations. A public Base Sepolia transaction would require test USDC for the buyer, Sepolia ETH for the relayer, wallet signatures, and a testnet relayer wired to the payment endpoint.

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
- An x402 v2 payment flow for a dated price comparison ([x402.py](proof/collateral_card/x402.py)).
- A fork replay that repays an Aave Mag7 loan from simulated x402 payment proceeds ([earned.py](proof/collateral_card/earned.py)).
- A guard that refuses any write path outside local loopback ([guard.py](proof/collateral_card/guard.py)).
- The interactive judge page in this repository.

To rerun both loans on a local fork, follow [the reproduction steps](proof/README.md). The rerun needs Foundry and native `solc` 0.8.20. It needs no wallet or API key, and it makes no mainnet transactions.

## Limits

- The results come from a local fork with a replayed oracle update. No real loan has been taken.
- The Aave and USDC contracts are the fork's. The collateral token and price feed are stand-ins.
- All 518 payments came from one simulated buyer. The original saved receipts used an acknowledgment endpoint. The current runner serves the historical price comparison. Customer demand and repayment economics are untested.
- The x402 server and facilitator run locally.
- At the replayed starting health, the rule repaid on 11 of 24 token-weekends (3 tokens over 8 calendar weekends). One repayment was needed and 10 were false alarms.
- The historic backtest calculation and its normalized snapshots are bundled here. The live collector and forecaster are outside the bundle. The local fork block identifies the receipt rerun. The original source request envelopes and collection blocks are unavailable.
