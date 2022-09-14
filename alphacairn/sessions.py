"""Build portable operator calendars and query retained session horizons."""

import argparse
import json
from pathlib import Path

from .execution_export import parse_data
from .session_calendar import SessionCalendar
from .session_model import MAX_BYTES, build_calendar


def main():
    parser = argparse.ArgumentParser(
        description="Explicit retained session schedules; no inferred holidays"
    )
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("definition", type=Path)
    build.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("document", type=Path)
    for action in ("session", "locate", "next-open", "advance"):
        command = sub.add_parser(action)
        command.add_argument("document", type=Path)
        command.add_argument("calendar")
        command.add_argument("value")
        if action == "next-open":
            command.add_argument("--exclusive", action="store_true")
        if action == "advance":
            command.add_argument("count", type=int)
            command.add_argument(
                "--roll", choices=("raise", "following", "preceding"), default="raise"
            )
    args = parser.parse_args()
    try:
        path = args.definition if args.action == "build" else args.document
        with path.open("rb") as stream:
            value = parse_data(stream.read(MAX_BYTES + 1), MAX_BYTES)
        if args.action == "build":
            result = build_calendar(value)
            # Exclusive creation preserves existing evidence; remove partial writes on error.
            created = False
            try:
                with args.output.open("x", encoding="utf-8") as stream:
                    created = True
                    stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
            except BaseException:
                if created:
                    args.output.unlink(missing_ok=True)
                raise
            result = {
                "path": str(args.output),
                "sha256": result["sha256"],
                "sessions": len(result["sessions"]),
            }
        else:
            index = SessionCalendar(value)
            if args.action == "verify":
                result = {
                    "passed": True,
                    "sha256": index.document["sha256"],
                    "source_authenticated": False,
                    "sessions": len(index.document["sessions"]),
                }
            elif args.action == "session":
                result = index.session(args.calendar, args.value)
            elif args.action == "locate":
                result = index.locate(args.calendar, args.value)
            elif args.action == "next-open":
                result = index.next_open(
                    args.calendar, args.value, inclusive=not args.exclusive
                )
            else:
                result = index.advance(
                    args.calendar, args.value, args.count, roll=args.roll
                )
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
