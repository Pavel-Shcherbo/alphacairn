import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alphacairn.portfolio import read_json

ROOT = Path(__file__).resolve().parents[1]


class PortfolioCliTests(unittest.TestCase):
    def call(self, db, *arguments):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "alphacairn.portfolio",
                "--db",
                str(db),
                *map(str, arguments),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_public_operator_lifecycle_reconciles_and_audits(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "account.sqlite"
            for arguments in [
                ("init", ROOT / "examples/portfolio-account.json"),
                ("apply", ROOT / "examples/portfolio-events.json"),
                ("reconcile", ROOT / "examples/portfolio-statement.json"),
                ("value", ROOT / "examples/portfolio-quotes.json"),
                ("audit",),
            ]:
                with self.subTest(arguments=arguments):
                    result = self.call(db, *arguments)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads(result.stdout)
                    if arguments[0] == "value":
                        self.assertEqual(report["equity"], "10948.90")
                    if arguments[0] == "audit":
                        self.assertTrue(report["passed"])
            events = self.call(db, "events", "--after", "3", "--limit", "2")
            report = json.loads(events.stdout)
            self.assertEqual(report["next_cursor"], 5)
            self.assertEqual(
                [item["event"]["id"] for item in report["events"]],
                ["sell-partial", "split"],
            )

    def test_missing_ledger_is_not_created_by_read_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "missing.sqlite"
            result = self.call(db, "state")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(db.exists())

    def test_json_boundary_rejects_duplicate_keys_nonfinite_and_deep_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            for payload in [
                '{"amount":"1","amount":"2"}',
                '{"amount":NaN}',
                "[" * 2000 + "0" + "]" * 2000,
            ]:
                path.write_text(payload)
                with self.subTest(payload=payload[:40]), self.assertRaises(ValueError):
                    read_json(path)
