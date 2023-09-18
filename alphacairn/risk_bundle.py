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


def write_risk(inputs, report, destination):
    replay = analyze_risk(inputs)
    if canonical(replay) != canonical(report):
        raise ValueError("risk report differs from fresh input replay")
    files = report_files(inputs, report)
    if (
        any(len(raw) > MAX_INPUT for raw in files.values())
        or sum(map(len, files.values())) > 48 * 1024 * 1024
    ):
        raise ValueError("risk bundle exceeds per-file/48 MiB limits")
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        manifest = {
            "format": "alphacairn.risk-bundle.v1",
            "inputs_sha256": inputs["sha256"],
            "report_sha256": report["sha256"],
            "files": {
                name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                for name, raw in sorted(files.items())
            },
        }
        manifest["sha256"] = digest(manifest)
        manifest_bytes = canonical(manifest) + b"\n"
        if sum(map(len, files.values())) + len(manifest_bytes) > 48 * 1024 * 1024:
            raise ValueError("risk bundle including manifest exceeds 48 MiB")
        for name, raw in files.items():
            with (destination / name).open("xb") as stream:
                stream.write(raw)
            (destination / name).chmod(0o600)
        (destination / "manifest.json").write_bytes(manifest_bytes)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {
        "path": str(destination),
        "complete": report["complete"],
        "report_sha256": report["sha256"],
        "files": sorted(files),
    }


def verify_risk_bundle(root):
    root = Path(root)
    if (
        root.is_symlink()
        or not root.is_dir()
        or {path.name for path in root.iterdir()} != FILES | {"manifest.json"}
    ):
        raise ValueError("risk bundle requires an exact ordinary file inventory")
    raw = {}
    for name in FILES | {"manifest.json"}:
        path = root / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > (65536 if name == "manifest.json" else MAX_INPUT)
        ):
            raise ValueError("risk bundle contains an unsafe/oversized file")
        raw[name] = path.read_bytes()
    if sum(map(len, raw.values())) > 48 * 1024 * 1024:
        raise ValueError("risk bundle exceeds 48 MiB")
    manifest = decode(raw["manifest.json"])
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {"format", "inputs_sha256", "report_sha256", "files", "sha256"}
        or manifest["format"] != "alphacairn.risk-bundle.v1"
        or manifest["sha256"]
        != digest({k: v for k, v in manifest.items() if k != "sha256"})
        or set(manifest["files"]) != FILES
    ):
        raise ValueError("risk manifest identity/fields mismatch")
    for name in FILES:
        if manifest["files"][name] != {
            "bytes": len(raw[name]),
            "sha256": hashlib.sha256(raw[name]).hexdigest(),
        }:
            raise ValueError("risk bundle file hash mismatch")
    inputs = bounded_json(decode(raw["inputs.json"]))
    report = bounded_json(decode(raw["risk-report.json"]))
    replay = analyze_risk(inputs)
    if (
        canonical(replay) != canonical(report)
        or report["sha256"] != manifest["report_sha256"]
        or inputs["sha256"] != manifest["inputs_sha256"]
    ):
        raise ValueError("risk numerical/journal replay differs from retained report")
    expected = report_files(inputs, report)
    if any(raw[name] != expected[name] for name in FILES):
        raise ValueError("risk bundle CSV/JSON bytes differ from replay")
    return {
        "passed": True,
        "complete": report["complete"],
        "journal_replayed": True,
        "numerical_replay_passed": True,
        "inputs_sha256": inputs["sha256"],
        "report_sha256": report["sha256"],
        "source_authenticated": False,
        "scope": "Fresh journal, valuation, stress and descriptive risk reconstruction; no authenticated external prices or forecast validation",
    }
