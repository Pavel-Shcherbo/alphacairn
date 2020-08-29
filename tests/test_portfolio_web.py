import unittest

from alphacairn.portfolio_web import portfolio_example
from alphacairn.web import evaluate


class PortfolioWorkbenchTests(unittest.TestCase):
    def test_default_scenario_has_exact_equity_and_reconciliation(self):
        report = evaluate({"mode": "portfolio"})
        self.assertTrue(report["passed"])
        self.assertEqual(report["valuation"]["equity"], "10948.90")
        self.assertEqual(len(report["receipts"]), 9)
        self.assertEqual(len(report["input_sha256"]), 64)
        self.assertTrue(report["audit"]["passed"])

    def test_missing_mark_preserves_journal_audit_but_fails_valuation(self):
        report = evaluate({"mode": "portfolio", "omit_crypto_mark": True})
        self.assertFalse(report["passed"])
        self.assertIsNone(report["valuation"]["equity"])
        self.assertTrue(report["audit"]["passed"])
        self.assertTrue(report["reconciliation"]["matched"])

