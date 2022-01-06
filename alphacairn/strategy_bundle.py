"""Portable strategy inputs, decision traces and independently replayed executions."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from .execution_export import (
    FILES as EXECUTION_FILES,
    csv_data,
    json_data,
    parse_data,
    verify_execution_bundle,
    write_execution,
)
from .market_model import MAX_BYTES, canonical, digest
from .strategy_engine import simulate_strategy
from .strategy_inputs import prepare_strategy_inputs

ROOT_FILES = frozenset({"inputs.json", "strategy-report.json", "decisions.csv"})
ALL_FILES = ROOT_FILES | {
    "execution/" + name for name in EXECUTION_FILES | {"manifest.json"}
}
TOTAL_LIMIT = 128 * 1024 * 1024


def decision_csv(report):
    rows = []
    for decision in report["decisions"]:
        for action in decision["actions"]:
            rows.append(
                {
                    "decision": decision["index"],
                    "at": decision["at"],
                    "session": decision["session"],
                    **action,
                    "pending_orders": ";".join(action["pending_orders"]),
                }
            )
    return csv_data(
        rows,
        [
            "decision",
            "at",
            "session",
            "instrument",
            "signal_reason",
            "current_quantity",
            "target_quantity",
            "delta_quantity",
            "outcome",
            "order_id",
            "pending_orders",
            "feature_snapshot_sha256",
        ],
    )


def write_strategy_inputs(document, destination):
    prepare_strategy_inputs(document)
    raw = json_data(document)
    if len(raw) > MAX_BYTES:
        raise ValueError("formatted strategy inputs exceed 16 MiB")
    destination = Path(destination)
    # A hard link publishes only a fully written file and never overwrites a peer.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".strategy-inputs-", dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "path": str(destination),
        "inputs_sha256": document["sha256"],
        "bytes": len(raw),
    }


