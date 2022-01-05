"""Capture, simulate and replay catalog-backed target-inventory studies."""

import argparse
import json
import sqlite3
from pathlib import Path

from .execution_export import parse_data
from .market_model import MAX_BYTES
from .market_store import MarketCatalog
from .strategy_bundle import (
    verify_strategy_bundle,
    write_strategy,
    write_strategy_inputs,
)
from .strategy_engine import simulate_strategy
from .strategy_inputs import capture_strategy


def main():
    parser = argparse.ArgumentParser(
        description="Replay decision-time signals separately from execution-price vintages"
    )
    sub = parser.add_subparsers(dest="action", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("definition", type=Path)
    capture.add_argument("--database", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("inputs", type=Path)
    run.add_argument("--output", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "verify":
            result = verify_strategy_bundle(args.directory)
        else:
            path = args.definition if args.action == "capture" else args.inputs
            with path.open("rb") as stream:
                definition = parse_data(stream.read(MAX_BYTES + 1), MAX_BYTES)
            if args.action == "capture":
                inputs = capture_strategy(MarketCatalog(args.database), definition)
                result = write_strategy_inputs(inputs, args.output)
            else:
                report = simulate_strategy(definition)
                result = (
                    write_strategy(definition, report, args.output)
                    if args.output
                    else report
                )
        print(json.dumps(result, indent=2, allow_nan=False))
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        OverflowError,
        sqlite3.Error,
    ) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
