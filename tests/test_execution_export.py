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

