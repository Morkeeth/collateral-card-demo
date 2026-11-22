# Collateral Card

A stock-backed loan can look healthy while its lending oracle still shows Friday's price. Collateral Card is an agent that watches the weekend gap and uses USDC earned from paid x402 quotes to reduce its debt before the oracle updates.

**Open the demo:** https://morkeeth.github.io/collateral-card-demo/

No wallet, account or install is needed. Entry for Base Stocks Maxxing, Agentic Stock Finance track.

## Result

This is a replay of the NVDAc weekend of 6 November 2026 on a local Base mainnet fork.

| | With quote income | Income removed |
| --- | ---: | ---: |
| Quotes sold | 518 | 0 |
| Income | 25.90 USDC | 0 USDC |
| Debt repaid | 25.87 USDC | 0 USDC |
| Health after the oracle update | 1.0851 | 0.9780 |
| Liquidation attempt | Refused | Succeeded |

## Built during the Quest Period

All of this work was written between 20 and 22 November 2026:

- A repayment rule that compares the market price with a frozen lending price ([rule.py](proof/collateral_card/rule.py)).
- An x402 v2 paid quote flow ([x402.py](proof/collateral_card/x402.py)).
- A fork replay that repays an Aave Mag7 loan from quote income ([earned.py](proof/collateral_card/earned.py)).
- A guard that refuses any write path outside local loopback ([guard.py](proof/collateral_card/guard.py)).
- The interactive judge page in this repository.

## Check it yourself

Check the saved results offline with Python 3.10 or later:

```sh
python3 proof/verify.py
```

To rerun both loans on a local fork, follow [the reproduction steps](proof/README.md). The rerun needs Foundry and native `solc` 0.8.20. It needs no wallet or API key, and it makes no mainnet transactions.

## Limits

- The results come from a local fork with a replayed oracle update. No real loan has been taken.
- The Aave and USDC contracts are the fork's. The collateral token and price feed are stand-ins.
- All 518 quote sales came from one simulated buyer. Customer demand and repayment economics are untested.
- The x402 server and facilitator run locally.
- At the replayed starting health, the rule repaid on 11 of 24 recorded weekends. One repayment was needed and 10 were false alarms.
- The weekend forecaster that produced the recorded estimate is outside this repository. Its output is saved in [inputs.json](proof/inputs.json).
