"""Create-only risk inputs/reports and fresh offline numerical reconstruction."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from .execution_export import csv_data
from .market_model import canonical, decode, digest
from .risk_engine import analyze_risk
from .risk_inputs import prepare_risk_inputs
from .risk_model import MAX_INPUT, bounded_json

FILES = frozenset(
    {"inputs.json", "risk-report.json", "exposures.csv", "stresses.csv", "history.csv"}
)


def save_risk_inputs(document, destination):
    prepare_risk_inputs(document)
    raw = canonical(document) + b"\n"
    if len(raw) > MAX_INPUT:
        raise ValueError("serialized risk inputs exceed 16 MiB")
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".risk-inputs-", dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"path": str(destination), "sha256": document["sha256"], "bytes": len(raw)}


def report_files(inputs, report):
    return {
        "inputs.json": canonical(inputs) + b"\n",
        "risk-report.json": canonical(report) + b"\n",
        "exposures.csv": csv_data(
            report["exposures"],
            [
                "id",
                "kind",
                "instrument",
                "currency",
                "venue",
                "asset_kind",
                "base_value",
            ],
        ),
        "stresses.csv": csv_data(
            report["stresses"], ["id", "complete", "equity", "pnl", "return"]
        ),
        "history.csv": csv_data(
            report["history"].get("intervals", []), ["from", "to", "pnl"]
        ),
    }


