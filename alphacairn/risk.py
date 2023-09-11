"""Capture, analyze and replay portable multi-asset risk studies."""

import argparse
import json
from pathlib import Path
import sqlite3

from .market_model import decode
from .risk_bundle import save_risk_inputs, write_risk, verify_risk_bundle
from .risk_engine import analyze_risk
from .risk_inputs import capture_risk_inputs
from .risk_model import MAX_INPUT, bounded_json


def load(path):
    with Path(path).open("rb") as stream:
        return bounded_json(decode(stream.read(MAX_INPUT + 1)))


def main():
    parser = argparse.ArgumentParser(
        description="Replay journal-backed multi-asset risk and explicit stress scenarios"
    )
    actions = parser.add_subparsers(dest="action", required=True)
    capture = actions.add_parser("capture")
    capture.add_argument("configuration", type=Path)
    capture.add_argument("--database", type=Path, required=True)
    capture.add_argument("--history", type=Path, required=True)
    capture.add_argument("--quotes", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    run = actions.add_parser("run")
    run.add_argument("inputs", type=Path)
    run.add_argument("--output", type=Path, required=True)
    inspect = actions.add_parser("inspect")
    inspect.add_argument("inputs", type=Path)
    verify = actions.add_parser("verify")
    verify.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "capture":
            document = capture_risk_inputs(
                args.database,
                load(args.configuration),
                load(args.history),
                load(args.quotes),
            )
            result = save_risk_inputs(document, args.output)
        elif args.action == "verify":
            result = verify_risk_bundle(args.directory)
        else:
            inputs = load(args.inputs)
            report = analyze_risk(inputs)
            if args.action == "run":
                result = write_risk(inputs, report, args.output)
            else:
                result = report
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result.get("complete", True) else 1
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        sqlite3.Error,
        OverflowError,
        RecursionError,
        ArithmeticError,
    ) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
