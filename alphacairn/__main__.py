import argparse
import hashlib
import json
from pathlib import Path

from .backtest import load_bars, simulate


def main():
    parser = argparse.ArgumentParser(
        description="Compare a lagged moving-average signal with buy-and-hold"
    )
    parser.add_argument("csv", type=Path)
    parser.add_argument("--lookback", type=int, default=3)
    parser.add_argument("--fee-bps", type=float, default=10)
    parser.add_argument("--slippage-bps", type=float, default=5)
    args = parser.parse_args()
    try:
        bars = load_bars(args.csv)
        options = {"fee_bps": args.fee_bps, "slippage_bps": args.slippage_bps}
        result = {
            "data_sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
            "parameters": vars(args) | {"csv": str(args.csv)},
            "strategy": simulate(bars, lookback=args.lookback, **options),
            "baseline": simulate(bars, buy_and_hold=True, **options),
        }
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(result, indent=2))


main()
