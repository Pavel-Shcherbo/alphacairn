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


