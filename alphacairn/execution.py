"""Run or independently replay a local multi-instrument order scenario."""

import argparse
import json
import sqlite3
from pathlib import Path

from .execution_engine import simulate_execution
from .execution_export import parse_data, verify_execution_bundle, write_execution


def main():
    parser = argparse.ArgumentParser(
        description="Simulate explicit long-only orders with bounded known liquidity"
    )
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run")
    run.add_argument("scenario", type=Path)
    run.add_argument("--output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "verify":
            result = verify_execution_bundle(args.directory)
        else:
            with args.scenario.open("rb") as stream:
                definition = parse_data(
                    stream.read(8 * 1024 * 1024 + 1), 8 * 1024 * 1024
                )
            report = simulate_execution(definition)
            result = (
                write_execution(definition, report, args.output)
                if args.output is not None
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
