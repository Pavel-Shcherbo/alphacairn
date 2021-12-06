"""Deterministic portable execution evidence, tampering and CLI lifecycle."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_export import verify_execution_bundle, write_execution
from test_execution import scenario


class ExecutionExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = scenario()
        self.report = simulate_execution(self.data)

    def test_complete_export_replays_byte_identically_without_overwrite(self):
        first = self.root / "first"
        second = self.root / "second"
        a = write_execution(self.data, self.report, first)
        b = write_execution(self.data, simulate_execution(self.data), second)
        self.assertEqual(a["files"], b["files"])
        self.assertEqual(
            (first / "manifest.json").read_bytes(),
            (second / "manifest.json").read_bytes(),
        )
        self.assertTrue(verify_execution_bundle(first)["passed"])
        with self.assertRaises(FileExistsError):
            write_execution(self.data, self.report, first)

    def test_csv_tampering_is_rejected_even_after_manifest_hash_is_updated(self):
        target = self.root / "bundle"
        write_execution(self.data, self.report, target)
        csv = target / "fills.csv"
        csv.write_bytes(csv.read_bytes().replace(b"50.00", b"49.00"))
        with self.assertRaisesRegex(ValueError, "hash"):
            verify_execution_bundle(target)
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["fills.csv"] = {
            "bytes": csv.stat().st_size,
            "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
        }
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "replay"):
            verify_execution_bundle(target)

    def test_incomplete_extra_files_and_symlinks_are_refused(self):
        target = self.root / "bundle"
        write_execution(self.data, self.report, target)
        extra = target / "unexpected"
        extra.write_text("extra")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            verify_execution_bundle(target)
        extra.unlink()
        report = target / "report.json"
        raw = report.read_bytes()
        report.unlink()
        external = self.root / "external"
        external.write_bytes(raw)
        report.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            verify_execution_bundle(target)

