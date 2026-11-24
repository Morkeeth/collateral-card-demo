# Reproduce the forecast and loan replay

## Verify the forecast and saved loan replay offline

From the repository root with Python 3.10 or later:

```sh
python3 -B proof/verify_judge.py
```

The first check rebuilds the saved forecast and backtest from the normalized source snapshots. The second compares the saved receipts with the judge display, checks the pinned block and tests the simulated payment and repayment amounts. The command reads local files and executes no chain calls. The optional fork steps below are a separate experiment.

The [weekend backtest source manifest](SOURCE-MANIFEST.md) lists the saved observations, the offline arithmetic check and two optional public source reads.

## Simulated payment replay

The judge page displays saved results from a local Base mainnet fork. The interactive rule and chart use recorded prices in the browser. [recorded-comparison.json](recorded-comparison.json) contains the same outcome fields as the page bundle, with local RPC addresses omitted.

The experiment replays the NVDAc weekend starting 6 November 2026. The oracle stand-in moves from $187.9661 to $183.0326. The agent supplies 2 stand-in NVDAc with target starting health 1.0042. Both trials move the borrowed USDC out of the agent's balance before any sales. One simulated buyer makes 518 x402 payments of 0.05 USDC to a demo endpoint in the paid trial. The endpoint in the original saved run returned the acknowledgment `{"ok":true}` and delivers no forecast. The control makes zero sales. [inputs.json](inputs.json) fixes these inputs and records the forecast estimate, forecast band, and collateral factor.

| Recorded outcome | Simulated payment income | Income removed |
| --- | ---: | ---: |
| Income | 25.90 USDC | 0 USDC |
| Debt repaid | 25.87 USDC | 0 USDC |
| Health after the replayed reopen | 1.0851 | 0.9780 |
| Liquidation attempt | Refused | Succeeded |

## Rerun on a local fork

Install Foundry with `anvil` and `cast` on your PATH, plus native Solidity `solc` 0.8.20. Anvil needs support for the Jovian hardfork. The replay was checked with Foundry build `f83bad9`. The runner was adapted from the original earned-income calculation and uses only Python's standard library, Foundry and the Solidity compiler. Run the scenarios separately from the repository root:

```sh
python3 proof/run_fork.py paid --out /tmp/collateral-paid
python3 proof/run_fork.py control --out /tmp/collateral-control
python3 proof/verify.py --fork-results \
  /tmp/collateral-paid/earned-receipt.json \
  /tmp/collateral-control/earned-receipt.json
```

The runner uses public Base RPC for historical reads at block 60423882. It checks the block hash and starts a disposable loopback Anvil instance for each trial. The original receipt did not record its fork block. This rerun pins a known block and compares the outcomes at the page's display precision. The [paired pinned receipts](pinned-comparison.json) reproduce both outcomes in the table. Accrued interest can change the last digits of raw balances.

The fork provides test accounts and gas. The collateral token, oracle, buyer and loan spend are stand-ins. The x402 server and settlement run on loopback. The test makes no mainnet transactions and requires no wallet or API key. It tests the repayment logic for this sample. The judge page also shows a separate borrowed-USDC comparison outside this runner.

The current runner returns the recorded Aave and DEX prices at the recorded quote time. The public testnet can be used as the read-only source for a local fork: `python3 -B proof/run_sepolia.py --out /tmp/collateral-paid-quote.json`. This checks one separate Circle test USDC checkout and leaves the original loan proof input files intact.
