# Alphacairn

Compare trading hypotheses under explicit timing and execution assumptions.

## Run the workbench

From a source checkout with Python 3.10 or later:

```sh
python3 -m alphacairn.web
```

Open http://127.0.0.1:8412. No third-party runtime packages are required.
The workbench is a local development application, not a hosted multi-user service.
Run it from the checkout: bundled examples are not yet distributed in an installed package.

## Workbench preview

![Local workbench](docs/workbench.png)

## Command line

```sh
python3 -m alphacairn examples/synthetic.csv --lookback 20
python3 -m unittest discover -s tests -v
```

## Implemented

Loads validated daily CSV bars, simulates a long-only moving-average signal with previous-close decisions and next-open fills, applies fixed fees and slippage, compares with buy-and-hold and exports the equity path, trade ledger, input hash and assumptions. The browser accepts a local CSV file and exposes the same calculation.

## Boundaries

The included data is a deterministic synthetic fixture, not exchange history. The simulator assumes fractional long-only positions, unlimited modeled liquidity and fixed costs. It does not yet handle dividends, splits, delistings, historical universes, funding or margin. No profitability or market-performance result is claimed. The final position is valued at the last close rather than forcibly sold.

## Development scope

[Architecture](docs/ARCHITECTURE.md) explains the current execution path.
[Product scope](docs/PRODUCT_SCOPE.md) describes the broader proposed subsystems.
[Weekly roadmap](docs/proposed-weekly-roadmap.csv) is a planning scenario.
[Tasks](TASKS.md) and [request register](REQUESTS.md) track actual status.

## History note

This repository was assembled starting in November 2026. Earlier Git timestamps,
where used, represent reconstructed development stages, not verified original
work in those years. The 2019–2026 roadmap is proposed scope, not a completed-work record.
