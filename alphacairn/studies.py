"""Declare, retain, select and audit frozen risk or strategy research attempts."""

import argparse
import json
from pathlib import Path
import sqlite3

from .execution_export import parse_data
from .market_model import canonical
from .study_store import StudyRegistry
from .study_runner import run_trial
from .study_evidence import (
    audit_study,
    export_trial,
    verify_study_export,
    MAX_EXPORT,
    compare_trials,
    events,
    check_chain,
)


def load(path, limit=16 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        return parse_data(stream.read(limit + 1), limit)


def main():
    parser = argparse.ArgumentParser(
        description="Retain complete frozen research attempts and registry-local holdout access"
    )
    parser.add_argument("--database", type=Path, default=Path(".local/studies.sqlite"))
    parser.add_argument("--project", default="local")
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("create")
    create.add_argument("definition", type=Path)
    register = commands.add_parser("register")
    register.add_argument("study")
    register.add_argument("inputs", type=Path)
    register.add_argument(
        "--partition", choices=["development", "holdout"], required=True
    )
    register.add_argument("--request-key", required=True)
    register.add_argument("--label", required=True)
    for action in ("overview", "audit", "events"):
        sub = commands.add_parser(action)
        sub.add_argument("study")
    for action in ("run", "inspect", "export", "recover", "select"):
        sub = commands.add_parser(action)
        sub.add_argument("trial")
        sub.add_argument("--actor", required=True)
        sub.add_argument("--reason", required=True)
        if action == "export":
            sub.add_argument("--output", type=Path, required=True)
        if action == "select":
            sub.add_argument("--study", required=True)
        if action == "recover":
            sub.add_argument("--generation", type=int, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("study")
    compare.add_argument("--actor", required=True)
    compare.add_argument("--reason", required=True)
    compare.add_argument("--include-holdout", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "verify":
            result = verify_study_export(load(args.file, MAX_EXPORT))
        else:
            registry = StudyRegistry(args.database)
            if args.action == "create":
                result = registry.create(args.project, load(args.definition))
            elif args.action == "register":
                result = registry.register(
                    args.project,
                    args.study,
                    load(args.inputs),
                    args.partition,
                    args.request_key,
                    args.label,
                )
            elif args.action == "overview":
                result = registry.overview(args.project, args.study)
            elif args.action == "compare":
                result = compare_trials(
                    registry,
                    args.project,
                    args.study,
                    actor=args.actor,
                    reason=args.reason,
                    include_holdout=args.include_holdout,
                )
            elif args.action == "events":
                items = events(registry, args.project, args.study)
                result = {"events": items, "head": check_chain(args.study, items)}
            elif args.action == "audit":
                _, _, proof = audit_study(registry, args.project, args.study)
                result = {
                    k: v for k, v in proof.items() if k not in ("contracts", "finished")
                }
            elif args.action == "select":
                result = registry.select(
                    args.project,
                    args.study,
                    args.trial,
                    actor=args.actor,
                    reason=args.reason,
                )
            elif args.action == "recover":
                result = registry.recover(
                    args.project,
                    args.trial,
                    args.generation,
                    actor=args.actor,
                    reason=args.reason,
                )
            elif args.action == "run":
                result = run_trial(
                    registry,
                    args.project,
                    args.trial,
                    actor=args.actor,
                    reason=args.reason,
                )
            elif args.action == "inspect":
                result = registry.read(
                    args.project, args.trial, actor=args.actor, reason=args.reason
                )
            else:
                document = export_trial(
                    registry,
                    args.project,
                    args.trial,
                    actor=args.actor,
                    reason=args.reason,
                )
                raw = canonical(document) + b"\n"
                if len(raw) > MAX_EXPORT:
                    raise ValueError("serialized study export exceeds 72 MiB")
                with args.output.open("xb") as stream:
                    stream.write(raw)
                args.output.chmod(0o600)
                result = {"path": str(args.output), "sha256": document["sha256"]}
        print(json.dumps(result, indent=2, allow_nan=False))
        if (
            result.get("status") in ("failed", "incomplete", "interrupted")
            or result.get("complete") is False
            or result.get("record", {}).get("status", "succeeded")
            in ("failed", "incomplete", "interrupted")
        ):
            return 1
        return 0
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        sqlite3.Error,
        RecursionError,
        ArithmeticError,
    ) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
