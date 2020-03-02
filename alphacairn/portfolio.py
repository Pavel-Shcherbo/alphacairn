"""Local portfolio operator CLI: journal, value, reconcile and independently audit."""

import argparse
import json
import math
import sqlite3
from pathlib import Path

from .ledger import Ledger
from .valuation import value_portfolio


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("portfolio input exceeds 2 MiB")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject(_):
        raise ValueError("portfolio input must contain finite JSON values")

    try:
        result = json.loads(
            raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=reject
        )
        pending = [(result, 0)]
        nodes = 0
        while pending:
            value, depth = pending.pop()
            nodes += 1
            if depth > 50 or nodes > 100000:
                raise ValueError("portfolio JSON exceeds depth or structure budget")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("portfolio input must contain finite values")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        return result
    except RecursionError as error:
        raise ValueError("portfolio input nesting exceeds the parser limit") from error


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Operate a local exact-decimal portfolio journal"
    )
    parser.add_argument("--db", type=Path, default=Path(".local/portfolio.sqlite"))
    actions = parser.add_subparsers(dest="action", required=True)
    initialize = actions.add_parser(
        "init", help="Create or reopen an identically configured account"
    )
    initialize.add_argument("account", type=Path)
    apply = actions.add_parser(
        "apply", help="Apply an event or an atomic batch of events"
    )
    apply.add_argument("events", type=Path)
    actions.add_parser("state")
    events = actions.add_parser("events")
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)
    reconciliation = actions.add_parser("reconcile")
    reconciliation.add_argument("statement", type=Path)
    valuation = actions.add_parser("value")
    valuation.add_argument("quotes", type=Path)
    actions.add_parser(
        "audit", help="Rebuild accepted events and compare all materialized state"
    )
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            ledger = Ledger(args.db, read_json(args.account))
            report = {"initialized": True, "account": ledger.spec.definition()}
        else:
            if not args.db.is_file():
                raise ValueError("ledger does not exist; initialize it first")
            ledger = Ledger(args.db)
            if args.action == "apply":
                events = read_json(args.events)
                report = {
                    "receipts": ledger.apply_batch(
                        events if isinstance(events, list) else [events]
                    )
                }
            elif args.action == "state":
                report = ledger.state()
            elif args.action == "events":
                rows = ledger.events(args.after, args.limit)
                report = {
                    "events": rows,
                    "next_cursor": rows[-1]["sequence"] if rows else args.after,
                }
            elif args.action == "reconcile":
                report = ledger.reconcile(read_json(args.statement))
            elif args.action == "value":
                quotes = read_json(args.quotes)
                if (
                    not isinstance(quotes, dict)
                    or set(quotes) - {"as_of", "marks", "fx", "max_age_seconds"}
                    or not {"as_of", "marks", "fx"} <= set(quotes)
                ):
                    raise ValueError(
                        "quotes require as_of, marks and FX with optional max_age_seconds"
                    )
                report = value_portfolio(
                    ledger.state(),
                    quotes["marks"],
                    quotes["fx"],
                    as_of=quotes["as_of"],
                    max_age_seconds=quotes.get("max_age_seconds", 86400),
                )
            else:
                report = ledger.audit()
        print(json.dumps(report, indent=2, allow_nan=False))
        if args.action == "reconcile":
            return 0 if report["matched"] else 1
        if args.action == "value":
            return 0 if report["complete"] else 1
        if args.action == "audit":
            return 0 if report["passed"] else 1
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
