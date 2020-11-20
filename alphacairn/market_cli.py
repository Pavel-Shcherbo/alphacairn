"""Operate explicit-source market catalogs without network access."""

import argparse
import json
import sqlite3
from pathlib import Path

from .market_model import MAX_BYTES, decode, verify_snapshot
from .market_research import decision_windows, read_snapshot, write_snapshot
from .market_store import MarketCatalog


def main():
    parser = argparse.ArgumentParser(
        description="Version local market observations and reconstruct information cutoffs"
    )
    parser.add_argument("--database", type=Path, default=Path(".local/market.sqlite"))
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("init")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("source")
    ingest.add_argument("kind", choices=["bar", "membership"])
    ingest.add_argument("file", type=Path)
    ingest.add_argument("--request-key", required=True)
    batches = sub.add_parser("batches")
    batches.add_argument("source")
    batches.add_argument("--after", default="")
    batches.add_argument("--limit", type=int, default=100)
    history = sub.add_parser("history")
    history.add_argument("source")
    history.add_argument("kind", choices=["bar", "membership"])
    history.add_argument("instrument")
    history.add_argument("--limit", type=int, default=1000)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("query", type=Path)
    snapshot.add_argument("--output", type=Path)
    verify = sub.add_parser("verify-snapshot")
    verify.add_argument("file", type=Path)
    windows = sub.add_parser("decision-windows")
    windows.add_argument("definition", type=Path)
    audit = sub.add_parser("audit")
    audit.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    def definition(path):
        with path.open("rb") as stream:
            return decode(stream.read(MAX_BYTES + 1))

    try:
        if args.action == "verify-snapshot":
            result = verify_snapshot(read_snapshot(args.file))
        else:
            catalog = MarketCatalog(args.database, create=args.action == "init")
            if args.action == "init":
                result = {"database": str(catalog.path), "initialized": True}
            elif args.action == "ingest":
                result = catalog.ingest_file(
                    args.source, args.kind, args.file, request_key=args.request_key
                )
            elif args.action == "batches":
                result = catalog.batches(
                    args.source, after=args.after, limit=args.limit
                )
            elif args.action == "history":
                result = catalog.history(
                    args.source, args.kind, args.instrument, limit=args.limit
                )
            elif args.action == "snapshot":
                result = catalog.snapshot(definition(args.query))
                if args.output:
                    result = write_snapshot(result, args.output)
            elif args.action == "decision-windows":
                specification = definition(args.definition)
                if not isinstance(specification, dict) or set(specification) != {
                    "source",
                    "universe",
                    "decisions",
                    "start",
                    "lookback",
                    "clock",
                }:
                    raise ValueError("invalid decision-window definition fields")
                result = decision_windows(catalog, **specification)
            else:
                result = catalog.audit(limit=args.limit)
        print(json.dumps(result, indent=2, allow_nan=False))
        if result.get("passed") is False:
            raise SystemExit(1)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        sqlite3.Error,
        OverflowError,
    ) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
