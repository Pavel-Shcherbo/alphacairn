"""Command-line descriptive analytics and sequential strategy evaluation."""

import argparse
import hashlib
import json
from pathlib import Path

from .analytics import (
    block_resample,
    compare,
    drawdown_history,
    rolling_volatility,
    summarize,
)
from .backtest import dataset_digest, load_bars, simulate
from .walkforward import walk_forward


def main():
    parser = argparse.ArgumentParser(description="Run an auditable local market study")
    parser.add_argument("action", choices=["risk", "walk-forward"])
    parser.add_argument("csv", type=Path)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--candidates", type=int, nargs="+", default=[5, 10, 20, 40])
    parser.add_argument("--train-size", type=int, default=100)
    parser.add_argument("--test-size", type=int, default=40)
    parser.add_argument(
        "--score", choices=["total_return", "sharpe"], default="total_return"
    )
    parser.add_argument("--periods-per-year", type=int, default=365)
    parser.add_argument("--fee-bps", type=float, default=10)
    parser.add_argument("--slippage-bps", type=float, default=5)
    parser.add_argument("--resample", action="store_true")
    args = parser.parse_args()
    try:
        bars = load_bars(args.csv)
        costs = {"fee_bps": args.fee_bps, "slippage_bps": args.slippage_bps}
        if args.action == "walk-forward":
            result = walk_forward(
                bars,
                args.candidates,
                args.train_size,
                args.test_size,
                score=args.score,
                periods_per_year=args.periods_per_year,
                **costs,
            )
        else:
            study = simulate(bars, lookback=args.lookback, **costs)
            baseline = simulate(bars, buy_and_hold=True, **costs)
            result = {
                "parameters": {
                    "lookback": args.lookback,
                    "periods_per_year": args.periods_per_year,
                    **costs,
                },
                "strategy": summarize(
                    study["equity"], study["initial_cash"], args.periods_per_year
                ),
                "baseline": summarize(
                    baseline["equity"], baseline["initial_cash"], args.periods_per_year
                ),
                "comparison": compare(
                    study["equity"],
                    baseline["equity"],
                    study["initial_cash"],
                    args.periods_per_year,
                ),
                "drawdowns": drawdown_history(study["equity"], study["initial_cash"]),
                "rolling_volatility": rolling_volatility(
                    study["equity"],
                    study["initial_cash"],
                    periods_per_year=args.periods_per_year,
                ),
            }
            if args.resample:
                result["resampled_total_returns"] = block_resample(
                    study["equity"], study["initial_cash"]
                )
        result["data_sha256"] = dataset_digest(bars)
        result["source_file_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
        result["digest_policy"] = (
            "Normalized date/open/close records plus a separate original-file hash"
        )
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, KeyError, OSError, OverflowError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
