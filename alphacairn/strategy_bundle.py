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


def write_strategy(inputs, report, destination):
    prepared = prepare_strategy_inputs(inputs)
    if (
        not isinstance(report, dict)
        or report.get("format") != "alphacairn.strategy-report.v1"
        or report.get("completed") is not True
        or report.get("planning_replayed") is not True
        or report.get("inputs_sha256") != prepared.sha256
        or report.get("configuration_sha256") != digest(prepared.configuration)
        or report.get("sha256")
        != digest({key: value for key, value in report.items() if key != "sha256"})
    ):
        raise ValueError("strategy report identity or input binding mismatch")
    if (
        report.get("windows") != prepared.windows
        or not isinstance(report.get("scenario"), dict)
        or {
            key: value for key, value in report["scenario"].items() if key != "commands"
        }
        != {
            key: value
            for key, value in prepared.execution.definition.items()
            if key != "commands"
        }
    ):
        raise ValueError(
            "strategy report differs from its captured signal or realization inputs"
        )
    files = {
        "inputs.json": json_data(inputs),
        "strategy-report.json": json_data(report),
        "decisions.csv": decision_csv(report),
    }
    if (
        len(files["inputs.json"]) > MAX_BYTES
        or len(files["strategy-report.json"]) > 32 * 1024 * 1024
        or len(files["decisions.csv"]) > 8 * 1024 * 1024
    ):
        raise ValueError("strategy export exceeds a file byte budget")
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("strategy destination cannot be a symbolic link")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        write_execution(
            report["scenario"], report["execution"], destination / "execution"
        )
        for name, raw in files.items():
            with (destination / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        metadata = {}
        total = 0
        for name in sorted(ALL_FILES):
            raw = (destination / name).read_bytes()
            total += len(raw)
            if total > TOTAL_LIMIT:
                raise ValueError("strategy bundle exceeds 128 MiB")
            metadata[name] = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        manifest = {
            "format": "alphacairn.strategy-bundle.v1",
            "inputs_sha256": prepared.sha256,
            "report_sha256": report["sha256"],
            "files": metadata,
        }
        with (destination / "manifest.json").open("xb") as stream:
            stream.write(json_data(manifest))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {"directory": str(destination), **manifest}


