"""Create-only deterministic execution bundles and independent scenario replay."""

import csv
import hashlib
import io
import json
import os
import shutil
from pathlib import Path

from .execution_engine import simulate_execution
from .execution_model import compile_execution
from .market_model import canonical, digest, pairs

FILE_LIMIT = 24 * 1024 * 1024
BUNDLE_LIMIT = 48 * 1024 * 1024
FILES = frozenset(
    {
        "scenario.json",
        "report.json",
        "ledger-events.json",
        "fills.csv",
        "orders.csv",
        "equity.csv",
    }
)


def json_data(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def parse_data(raw, limit=FILE_LIMIT):
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise ValueError("execution JSON file exceeds its byte limit")
    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ValueError("non-finite execution JSON")
            ),
        )
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid or excessively nested execution JSON") from error


def csv_data(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return stream.getvalue().encode()


def payloads(definition, report):
    plan = compile_execution(definition)
    if (
        not isinstance(report, dict)
        or report.get("format") != "alphacairn.execution-report.v1"
        or report.get("scenario_sha256") != plan.sha256
        or report.get("completed") is not True
        or report.get("accounting_reconciled") is not True
        or report.get("sha256")
        != digest({key: value for key, value in report.items() if key != "sha256"})
    ):
        raise ValueError("execution report identity or completion fields are invalid")
    result = {
        "scenario.json": json_data(plan.definition),
        "report.json": json_data(report),
        "ledger-events.json": json_data(report["ledger_events"]),
        "fills.csv": csv_data(
            report["fills"],
            [
                "id",
                "order_id",
                "instrument",
                "side",
                "at",
                "phase",
                "session",
                "quantity",
                "price",
                "notional",
                "fee",
                "currency",
                "cash_after",
                "position_after",
            ],
        ),
        "orders.csv": csv_data(
            report["orders"],
            [
                "id",
                "instrument",
                "side",
                "kind",
                "at",
                "time_in_force",
                "status",
                "quantity",
                "filled_quantity",
                "remaining_quantity",
                "average_fill_price",
                "fees",
                "attempts",
                "last_block_reason",
                "completed_at",
            ],
        ),
        "equity.csv": csv_data(
            report["equity_curve"],
            [
                "at",
                "complete",
                "equity",
                "known_base_value",
                "missing_count",
                "missing_diagnostics_complete",
            ],
        ),
    }
    if (
        any(len(value) > FILE_LIMIT for value in result.values())
        or len(result["scenario.json"]) > 8 * 1024 * 1024
        or sum(map(len, result.values())) > BUNDLE_LIMIT
    ):
        raise ValueError(
            "rendered execution bundle exceeds file or combined byte budget"
        )
    return plan, result


def write_execution(definition, report, destination):
    plan, files = payloads(definition, report)
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        for name, raw in files.items():
            with (destination / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        manifest = {
            "format": "alphacairn.execution-bundle.v1",
            "scenario_sha256": plan.sha256,
            "report_sha256": report["sha256"],
            "files": {
                name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                for name, raw in sorted(files.items())
            },
        }
        raw = json_data(manifest)
        # Manifest is the final completion marker; readers reject incomplete bundles.
        with (destination / "manifest.json").open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {
        "directory": str(destination),
        "scenario_sha256": plan.sha256,
        "report_sha256": report["sha256"],
        "files": manifest["files"],
    }


def verify_execution_bundle(directory, *, should_cancel=None):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("execution bundle must be an ordinary directory")
    if {path.name for path in directory.iterdir()} != FILES | {"manifest.json"}:
        raise ValueError(
            "execution bundle is incomplete or contains unexpected entries"
        )

    def read(name, limit):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("execution bundle files cannot be symlinks or directories")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("execution bundle file exceeds its byte budget")
        return raw

    manifest = parse_data(read("manifest.json", 65536), 65536)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"format", "scenario_sha256", "report_sha256", "files"}
        or manifest["format"] != "alphacairn.execution-bundle.v1"
        or not isinstance(manifest["files"], dict)
        or set(manifest["files"]) != FILES
    ):
        raise ValueError("invalid execution bundle manifest")
    files = {}
    total = 0
    for name, expected in manifest["files"].items():
        raw = read(name, 8 * 1024 * 1024 if name == "scenario.json" else FILE_LIMIT)
        total += len(raw)
        if total > BUNDLE_LIMIT:
            raise ValueError("execution bundle exceeds 48 MiB")
        if (
            not isinstance(expected, dict)
            or set(expected) != {"bytes", "sha256"}
            or type(expected["bytes"]) is not int
            or expected["bytes"] != len(raw)
            or expected["sha256"] != hashlib.sha256(raw).hexdigest()
        ):
            raise ValueError("execution bundle file hash or size mismatch: " + name)
        files[name] = raw
    definition = parse_data(files["scenario.json"], 8 * 1024 * 1024)
    saved = parse_data(files["report.json"])
    # Re-execute inputs rather than treating a self-consistent manifest as proof.
    replayed = simulate_execution(definition, should_cancel=should_cancel)
    plan, expected = payloads(definition, replayed)
    if (
        manifest["scenario_sha256"] != plan.sha256
        or manifest["report_sha256"] != replayed["sha256"]
        or saved != replayed
        or files != expected
    ):
        raise ValueError(
            "saved execution output differs from deterministic scenario replay"
        )
    return {
        "passed": True,
        "replayed": True,
        "scenario_sha256": plan.sha256,
        "report_sha256": replayed["sha256"],
        "fills": len(replayed["fills"]),
        "open_orders": replayed["open_order_count"],
        "accounting_reconciled": replayed["accounting_reconciled"],
        "valuation_complete": replayed["valuation"]["complete"],
    }
