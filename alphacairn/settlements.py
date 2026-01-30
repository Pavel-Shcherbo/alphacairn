"""Preview declared cash due dates and settle a persistent journal explicitly."""

import argparse
import json
from pathlib import Path
import sqlite3

from .execution_export import parse_data
from .instruments import AccountSpec
from .ledger import Ledger
from .settlement_clock import SettlementClock
from .settlement_service import SettlementService


def load(path):
    with path.open("rb") as stream:
        return parse_data(stream.read(8 * 1024 * 1024 + 1), 8 * 1024 * 1024)


def main():
    cli = argparse.ArgumentParser(
        description="Explicit-clock cash settlement and retained calendar preview"
    )
    commands = cli.add_subparsers(dest="action", required=True)
    due = commands.add_parser("due")
    due.add_argument("policy", type=Path)
    due.add_argument("--account", type=Path, required=True)
    due.add_argument("--instrument", required=True)
    due.add_argument("--at", required=True)
    due.add_argument("--session", required=True)
    pending = commands.add_parser("pending")
    pending.add_argument("--db", type=Path, required=True)
    settle = commands.add_parser("settle-due")
    settle.add_argument("--db", type=Path, required=True)
    settle.add_argument("--at", required=True)
    settle.add_argument("--request-key", required=True)
    settle.add_argument("--limit", type=int, default=100)
    receipt = commands.add_parser("receipt")
    receipt.add_argument("--db", type=Path, required=True)
    receipt.add_argument("request_key")
    args = cli.parse_args()
    try:
        if args.action == "due":
            result = SettlementClock(
                load(args.policy), AccountSpec.compile(load(args.account))
            ).due(args.instrument, args.at, args.session)
        elif args.action == "pending":
            state = Ledger(args.db).state()
            result = {
                "sequence": state["last_sequence"],
                "latest_timestamp": state["latest_timestamp"],
                "settlement": state.get("settlement", {"cash": [], "pending": []}),
            }
        else:
            service = SettlementService(args.db)
            result = (
                service.receipt(args.request_key)
                if args.action == "receipt"
                else service.settle_due(args.at, args.request_key, limit=args.limit)
            )
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        cli.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
