"""Independent cash controls and adversarial decision-versus-execution clocks."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal, Inexact, localcontext
from pathlib import Path

from alphacairn.execution_export import json_data
from alphacairn.market_model import canonical, digest, snapshot_identity
from alphacairn.market_store import MarketCatalog
from alphacairn.strategy_bundle import (
    verify_strategy_bundle,
    write_strategy,
    write_strategy_inputs,
)
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_inputs import (
    capture_strategy,
    compile_strategy,
    prepare_strategy_inputs,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


def rehash_inputs(document):
    document["sha256"] = digest(
        {key: value for key, value in document.items() if key != "sha256"}
    )


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = MarketCatalog(self.root / "market.sqlite", create=True)
        self.definition = load("strategy-control.json")
        self.bars = load("strategy-bars.json")
        self.members = load("strategy-universe.json")
        self.ingest(self.bars, "bar", "bars")
        self.ingest(self.members, "membership", "members")

    def ingest(self, rows, kind="bar", key="revision"):
        return self.catalog.ingest(
            self.definition["source"], kind, canonical(rows), request_key=key
        )

    def run_study(self, definition=None):
        inputs = capture_strategy(self.catalog, definition or self.definition)
        return inputs, simulate_strategy(inputs)

    def test_hand_calculated_six_fills_cash_positions_and_equity(self):
        inputs, result = self.run_study()
        execution = result["execution"]
        self.assertTrue(result["planning_replayed"])
        self.assertTrue(execution["ledger_audit"]["passed"])
        expected = [
            ("STOCK-A", "buy", "2", "13"),
            ("COIN-C", "buy", "1.0", "23"),
            ("STOCK-A", "sell", "2", "9"),
            ("COIN-C", "buy", "0.5", "25"),
            ("STOCK-A", "buy", "3", "15"),
            ("COIN-C", "sell", "1.5", "20"),
        ]
        self.assertEqual(
            [
                (fill["instrument"], fill["side"], fill["quantity"], fill["price"])
                for fill in execution["fills"]
            ],
            expected,
        )
        # Independent integer cents: 10000-2650-2350+1750-1300-4550+2950.
        self.assertEqual(execution["cash"], {"USD": "38.50"})
        self.assertEqual(execution["valuation"]["equity"], "86.50")
        self.assertEqual(execution["positions"]["STOCK-A"]["quantity"], "3")
        self.assertEqual(execution["fees_by_currency"], {"USD": "3.00"})
        self.assertEqual(prepare_strategy_inputs(inputs).sha256, inputs["sha256"])

    def test_next_decision_sizes_from_partial_fills_instead_of_requested_inventory(
        self,
    ):
        _, result = self.run_study()
        decision = result["decisions"][1]
        self.assertEqual(Decimal(decision["positions_before"]["STOCK-A"]), Decimal(2))
        self.assertEqual(Decimal(decision["positions_before"]["COIN-C"]), Decimal(1))
        actions = {item["instrument"]: item for item in decision["actions"]}
        self.assertEqual(actions["STOCK-A"]["delta_quantity"], "-2")
        self.assertEqual(Decimal(actions["COIN-C"]["delta_quantity"]), Decimal("0.5"))
        self.assertEqual(result["execution"]["orders"][0]["status"], "cancelled")

    def test_future_realization_revision_changes_valuation_not_earlier_signals_or_orders(
        self,
    ):
        _, before = self.run_study()
        revised = copy.deepcopy(
            next(
                row
                for row in self.bars
                if row["instrument"] == "STOCK-A" and row["session"] == "2020-01-06"
            )
        )
        revised.update(close="999", published_at="2020-01-07T12:00:00Z")
        self.ingest([revised])
        _, after = self.run_study()
        self.assertEqual(before["windows"], after["windows"])
        self.assertEqual(before["decisions"], after["decisions"])
        self.assertEqual(before["scenario"]["commands"], after["scenario"]["commands"])
        self.assertEqual(before["execution"]["fills"], after["execution"]["fills"])
        self.assertNotEqual(
            before["execution"]["valuation"]["equity"],
            after["execution"]["valuation"]["equity"],
        )

    def test_future_open_changes_later_balances_without_rewriting_first_decision(self):
        _, before = self.run_study()
        revised = copy.deepcopy(
            next(
                row
                for row in self.bars
                if row["instrument"] == "STOCK-A" and row["session"] == "2020-01-03"
            )
        )
        revised.update(open="100", published_at="2020-01-07T12:00:00Z")
        self.ingest([revised])
        _, after = self.run_study()
        self.assertEqual(before["decisions"][0], after["decisions"][0])
        self.assertEqual(
            before["scenario"]["commands"][:2], after["scenario"]["commands"][:2]
        )
        self.assertEqual(before["windows"], after["windows"])
        self.assertNotEqual(
            before["decisions"][1]["positions_before"],
            after["decisions"][1]["positions_before"],
        )

