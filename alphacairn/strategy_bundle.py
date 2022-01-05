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


