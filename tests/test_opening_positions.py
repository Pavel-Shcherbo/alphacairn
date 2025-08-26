"""Opening inventory controls independent of simulated trade funding."""

import copy
import csv
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext, Inexact
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_export import write_execution, verify_execution_bundle
from alphacairn.execution_model import compile_execution
from alphacairn.ledger import Ledger, normalize_event
from alphacairn.market_store import MarketCatalog
from alphacairn.market_model import canonical
from alphacairn.portfolio_web import evaluate_portfolio
from alphacairn.risk_journal import capture_journal
from alphacairn.study_model import trial_contract
from alphacairn.strategy_inputs import capture_strategy
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_bundle import write_strategy, verify_strategy_bundle
from test_corporate import split, dividend
from test_execution import scenario, bar, order
from test_strategy import load


def control():
    return load("opening-execution.json")


def event(name="lot", acquired="2019-01-01T00:00:00Z", quantity="5", basis="40.01"):
    return {
        "id": name,
        "timestamp": "2020-01-01T00:00:00Z",
        "kind": "opening_lot",
        "instrument": "A",
        "quantity": quantity,
        "basis": basis,
        "acquired_at": acquired,
    }


class OpeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = Ledger(self.root / "ledger.sqlite", control()["account"])

    def test_opening_does_not_spend_cash_or_make_a_trade(self):
        receipt = self.ledger.apply(event())
        state = self.ledger.state()
        self.assertEqual(state["cash"], {})
        self.assertEqual(state["positions"]["A"], {"quantity": "5", "basis": "40.01"})
        self.assertEqual(
            state["accounts"]["USD"],
            {"external_capital": "-40.01", "inventory:A": "40.01"},
        )
        self.assertEqual(state["lots"][0]["acquired_at"], "2019-01-01T00:00:00.000000Z")
        self.assertEqual(sum(Fraction(p["amount"]) for p in receipt["postings"]), 0)
        self.assertTrue(self.ledger.audit()["passed"])

    def test_initial_lots_sorted_by_acquisition_independent_of_input_order(self):
        compiled = compile_execution(control())
        self.assertEqual(
            [row["id"] for row in compiled.definition["initial_lots"]],
            ["old", "recent"],
        )
        other = control()
        other["initial_lots"].reverse()
        self.assertEqual(compiled.sha256, compile_execution(other).sha256)
        self.assertEqual(
            compiled.definition, compile_execution(compiled.definition).definition
        )

    def test_fifo_sale_then_purchase_matches_integer_cent_controls(self):
        result = simulate_execution(control())
        self.assertEqual(result["cash"], {"USD": "5.00"})
        self.assertEqual(result["positions"]["A"], {"quantity": "4", "basis": "42.50"})
        self.assertEqual(
            result["ledger_state"]["accounts"]["USD"]["realized_income:A"], "-7.49"
        )
        self.assertEqual(result["equity_curve"][0]["equity"], "40.00")
        self.assertEqual(result["valuation"]["equity"], "53.00")
        self.assertEqual(
            [row["kind"] for row in result["ledger_events"]],
            ["opening_lot", "opening_lot", "trade", "trade"],
        )
        self.assertEqual(len(result["fills"]), 2)
        self.assertEqual(result["fees_by_currency"], {"USD": "1.00"})
        self.assertEqual(
            result["opening_holdings"]["basis_by_currency"], {"USD": "40.01"}
        )
        self.assertFalse(result["opening_holdings"]["basis_is_market_value"])
        self.assertTrue(result["ledger_audit"]["passed"])

    def test_opening_cost_zero_is_not_missing_basis(self):
        self.ledger.apply(event(basis="0"))
        self.ledger.apply(
            {
                "id": "sell",
                "timestamp": "2020-01-02T00:00:00Z",
                "kind": "trade",
                "instrument": "A",
                "side": "sell",
                "quantity": "1",
                "price": "10",
                "fee": "0.50",
            }
        )
        self.assertEqual(self.ledger.state()["positions"]["A"]["basis"], "0.00")
        self.assertEqual(
            self.ledger.state()["accounts"]["USD"]["realized_income:A"], "-9.50"
        )
        self.assertTrue(self.ledger.audit()["passed"])

    def test_partial_basis_rounding_keeps_residual_cent(self):
        self.ledger.apply(event(quantity="2", basis="13.01"))
        self.ledger.apply(
            {
                "id": "s1",
                "timestamp": "2020-01-02T00:00:00Z",
                "kind": "trade",
                "instrument": "A",
                "side": "sell",
                "quantity": "1",
                "price": "10",
            }
        )
        self.assertEqual(self.ledger.state()["positions"]["A"]["basis"], "6.51")
        self.ledger.apply(
            {
                "id": "s2",
                "timestamp": "2020-01-03T00:00:00Z",
                "kind": "trade",
                "instrument": "A",
                "side": "sell",
                "quantity": "1",
                "price": "10",
            }
        )
        self.assertEqual(self.ledger.state()["positions"], {})
        self.assertEqual(
            self.ledger.state()["accounts"]["USD"]["realized_income:A"], "-6.99"
        )

    def test_concurrent_same_opening_receipt_creates_one_lot(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.ledger.apply(event()), range(4)))
        self.assertEqual(sum(not r["duplicate"] for r in receipts), 1)
        self.assertEqual(len(self.ledger.state()["lots"]), 1)
        changed = event(basis="40.02")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.ledger.apply(changed)

