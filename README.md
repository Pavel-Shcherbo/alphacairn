# Alphacairn

Compare trading hypotheses under explicit timing and execution assumptions.

## Run the workbench

From a source checkout with Python 3.10 or later:

```sh
python3 -m alphacairn.web
```

Open http://127.0.0.1:8412. No third-party runtime packages are required.
The workbench is a local development application, not a hosted multi-user service.
Bundled examples are included in the wheel. Runtime state is stored outside the installed package.

## Workbench preview

![Local workbench](docs/workbench.png)

## Command line

```sh
python3 -m alphacairn examples/synthetic.csv --lookback 20
python3 -m unittest discover -s tests -v
```

## Implemented

Loads validated daily CSV bars, simulates a long-only moving-average signal with previous-close decisions and next-open fills, applies fixed fees and slippage, compares with buy-and-hold and exports the equity path, trade ledger, input hash and assumptions. The browser accepts a local CSV file and exposes the same calculation.

## Portfolio journal

The workbench includes an exact-decimal portfolio section with FIFO lots, quote-currency commissions, splits, explicit dividends, FX cash movements, statement reconciliation and independent event replay. It supports synthetic equity and spot-crypto examples across USD/EUR, including missing-price and statement-difference controls.

For a persistent local account, use `python3 -m alphacairn.portfolio --help`. The [portfolio guide](docs/PORTFOLIO.md) provides the complete example, event contracts, rounding rules, valuation policy and current limits.

## Boundaries

The included data is a deterministic synthetic fixture, not exchange history. The simulator assumes fractional long-only positions, unlimited modeled liquidity and fixed costs. It does not yet handle dividends, splits, delistings, historical universes, funding or margin. No profitability or market-performance result is claimed. The final position is valued at the last close rather than forcibly sold.


## Sequential research and risk

```sh
python3 -m alphacairn.research risk examples/synthetic.csv --resample
python3 -m alphacairn.research walk-forward examples/synthetic.csv --train-size 100 --test-size 40
```

The workbench supports fixed parameters and trailing-window selection. Risk reports include stated-frequency annualization, drawdowns, paired baseline diagnostics and historical tail statistics. Window-end liquidation includes costs; a final untouched holdout is not reserved automatically. Dataset hashes normalize date/open/close records; original file or received-text hashes are retained separately. See [research method](docs/RESEARCH.md).

## Installed examples

```sh
python3 -m alphacairn.resources ./demo
```

This exports the reviewed examples to a new directory without overwriting an existing destination. Use the exported paths with the CLI.

## Development scope

[Architecture](docs/ARCHITECTURE.md) explains the current execution path.
[Product scope](docs/PRODUCT_SCOPE.md) describes the broader proposed subsystems.
[Weekly roadmap](docs/proposed-weekly-roadmap.csv) is a planning scenario.
[Tasks](TASKS.md) and [request register](REQUESTS.md) track actual status.

## History note

This repository was assembled starting in November 2026. Earlier Git timestamps,
where used, represent reconstructed development stages, not verified original
work in those years. The 2019–2026 roadmap is proposed scope, not a completed-work record.
