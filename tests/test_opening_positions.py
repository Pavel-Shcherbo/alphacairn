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

