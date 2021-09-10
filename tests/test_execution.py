"""Hand-calculated execution controls independent of descriptive strategy metrics."""

import copy
import tempfile
import unittest
from decimal import Decimal, localcontext, Inexact
from pathlib import Path

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_model import compile_execution


def instrument(name="A", currency="USD", step="1", tick="0.01"):
    return {
        "id": name,
        "symbol": name,
        "venue": "DEMO",
        "kind": "equity",
        "quote_currency": currency,
        "quantity_step": step,
        "price_tick": tick,
    }


def bar(day=2, name="A", opening="10", close="11", low="8", high="12", liquidity="100"):
    session = f"2020-01-{day:02d}"
    return {
        "instrument": name,
        "session": session,
        "opened_at": session + "T09:00:00Z",
        "closed_at": session + "T17:00:00Z",
        "open": opening,
        "high": high,
        "low": low,
        "close": close,
        "liquidity": liquidity,
        "liquidity_known_at": session + "T08:00:00Z",
    }


def order(
    name="buy",
    quantity="5",
    side="buy",
    kind="market",
    limit=None,
    tif="GTC",
    at="2020-01-01T12:00:00Z",
    asset="A",
    expires=None,
):
    return {
        "action": "submit",
        "id": name,
        "at": at,
        "instrument": asset,
        "side": side,
        "kind": kind,
        "quantity": quantity,
        "limit": limit,
        "time_in_force": tif,
        "expires_at": expires,
    }


def scenario():
    return {
        "version": 1,
        "account": {
            "name": "execution",
            "base_currency": "USD",
            "currencies": {"USD": 2},
            "instruments": [instrument()],
        },
        "starts_at": "2020-01-01T00:00:00Z",
        "ends_at": "2020-01-04T17:00:00Z",
        "initial_cash": {"USD": "100"},
        "fees": {"rate_bps": "0", "minimum": {}},
        "slippage_bps": "0",
        "max_mark_age_seconds": 86400 * 5,
        "bars": [bar()],
        "commands": [order()],
        "fx": [],
    }


class ExecutionTests(unittest.TestCase):
    def test_hand_calculated_purchase_and_journal_reconciliation(self):
        result = simulate_execution(scenario())
        self.assertEqual(result["cash"], {"USD": "50.00"})
        self.assertEqual(result["positions"]["A"], {"quantity": "5", "basis": "50.00"})
        self.assertEqual(result["valuation"]["equity"], "105.00")
        self.assertTrue(result["ledger_audit"]["passed"])
        self.assertTrue(result["accounting_reconciled"])

    def test_initial_cash_competing_assets_use_command_priority_not_symbol_order(self):
        data = scenario()
        data["account"]["instruments"].append(instrument("B"))
        data["bars"] = [bar(name="A"), bar(name="B")]
        data["commands"] = [
            order("first", quantity="8", asset="B"),
            order("second", quantity="8", asset="A"),
        ]
        result = simulate_execution(data)
        self.assertEqual(
            [(f["instrument"], f["quantity"]) for f in result["fills"]],
            [("B", "8"), ("A", "2")],
        )
        self.assertEqual(result["cash"]["USD"], "0.00")
        data["bars"].reverse()
        self.assertEqual(simulate_execution(data)["sha256"], result["sha256"])

    def test_partial_fills_share_liquidity_and_charge_each_minimum_fee(self):
        data = scenario()
        data["initial_cash"]["USD"] = "1000"
        data["fees"]["minimum"] = {"USD": "1"}
        data["bars"] = [
            bar(liquidity="2"),
            bar(3, liquidity="2"),
            bar(4, liquidity="2"),
        ]
        result = simulate_execution(data)
        self.assertEqual(
            [fill["quantity"] for fill in result["fills"]], ["2", "2", "1"]
        )
        self.assertEqual(result["fees_by_currency"]["USD"], "3.00")
        self.assertEqual(result["cash"]["USD"], "947.00")
        self.assertEqual(result["orders"][0]["status"], "filled")

    def test_no_same_open_or_intrabar_submission_fill(self):
        data = scenario()
        data["bars"] = [bar(), bar(3)]
        data["commands"] = [order(at="2020-01-02T09:00:00Z")]
        result = simulate_execution(data)
        self.assertEqual(result["fills"][0]["at"], "2020-01-03T09:00:00.000000Z")
        data["commands"][0]["at"] = "2020-01-02T12:00:00Z"
        self.assertEqual(
            simulate_execution(data)["fills"][0]["at"], "2020-01-03T09:00:00.000000Z"
        )

    def test_limit_touch_occurs_at_close_without_open_lookahead(self):
        data = scenario()
        data["commands"] = [order(kind="limit", limit="9")]
        result = simulate_execution(data)
        fill = result["fills"][0]
        self.assertEqual(fill["phase"], "limit_touch_at_close")
        self.assertEqual(fill["at"], "2020-01-02T17:00:00.000000Z")
        self.assertEqual(fill["price"], "9")
        self.assertEqual(result["cash"]["USD"], "55.00")

    def test_limit_gap_improvement_and_slippage_never_break_limit(self):
        data = scenario()
        data["commands"] = [order(kind="limit", limit="11")]
        data["slippage_bps"] = "2000"
        fill = simulate_execution(data)["fills"][0]
        self.assertEqual(fill["price"], "11")
        self.assertEqual(fill["phase"], "open")
        data["slippage_bps"] = "0"
        self.assertEqual(simulate_execution(data)["fills"][0]["price"], "10")

