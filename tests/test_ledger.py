import sqlite3
from contextlib import closing
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alphacairn.instruments import AccountSpec
from alphacairn.ledger import Ledger
from portfolio_fixtures import account_spec, event, trade, scenario_events


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "ledger.sqlite"
        self.ledger = Ledger(self.path, account_spec())

    def fund(self, amount="10000"):
        return self.ledger.apply(
            event("fund", "deposit", currency="USD", amount=amount)
        )

    def test_fifo_partial_sale_reconciles_hand_calculated_values(self):
        receipts = self.ledger.apply_batch(scenario_events()[:4])
        state = self.ledger.state()
        self.assertEqual(state["cash"]["USD"], "10194.00")
        self.assertEqual(
            state["positions"]["equity:demo-us"], {"quantity": "3", "basis": "360.60"}
        )
        self.assertEqual(
            [match["basis"] for match in receipts[3]["fifo_matches"]],
            ["1002.00", "240.40"],
        )
        self.assertEqual(
            state["accounts"]["USD"]["realized_income:equity:demo-us"], "-554.60"
        )
        self.assertTrue(self.ledger.audit()["passed"])

    def test_full_multi_currency_crypto_and_actions_scenario(self):
        self.ledger.apply_batch(scenario_events())
        state = self.ledger.state()
        self.assertEqual(state["cash"], {"EUR": "399.00", "USD": "7200.00"})
        self.assertEqual(
            state["positions"]["equity:demo-us"], {"quantity": "6", "basis": "360.60"}
        )
        self.assertEqual(
            state["positions"]["equity:demo-eu"], {"quantity": "10", "basis": "501.00"}
        )
        self.assertEqual(
            state["positions"]["crypto:demo"], {"quantity": "0.1", "basis": "2002.00"}
        )
        self.assertEqual(state["accounts"]["USD"]["dividend_income"], "-12.00")
        self.assertEqual(state["accounts"]["USD"]["withholding"], "3.00")
        self.assertTrue(Ledger(self.path).audit()["passed"])

    def test_duplicate_payload_is_idempotent_and_conflict_is_rejected(self):
        receipt = self.fund()
        repeated = self.ledger.apply(
            event("fund", "deposit", currency="USD", amount="10000.00")
        )
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(repeated["sequence"], receipt["sequence"])
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.ledger.apply(event("fund", "deposit", currency="USD", amount="9999"))
        self.assertEqual(self.ledger.state()["cash"]["USD"], "10000.00")

