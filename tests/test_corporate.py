"""Independent cash/unit controls for declared corporate actions and receivables."""

import copy
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal, localcontext, Inexact

from alphacairn.corporate_signals import signal_prices
from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_export import write_execution, verify_execution_bundle
from alphacairn.execution_model import compile_execution
from alphacairn.ledger import Ledger
from alphacairn.market_model import canonical
from alphacairn.market_store import MarketCatalog
from alphacairn.strategy_inputs import capture_strategy
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_bundle import write_strategy, verify_strategy_bundle
from alphacairn.valuation import value_portfolio
from test_execution import scenario, bar, order, instrument
from test_strategy import load


def control():
    return load("corporate-execution.json")


def simple(actions):
    value = scenario()
    value.update(
        version=3,
        calendar=None,
        calendar_policy=None,
        price_basis="unadjusted",
        corporate_actions=copy.deepcopy(actions),
    )
    return value


def split(at="2020-01-03T08:00:00Z", n=2, d=1, policy="adjust"):
    return {
        "kind": "split",
        "id": "split",
        "instrument": "A",
        "known_at": "2020-01-01T00:00:00Z",
        "at": at,
        "numerator": n,
        "denominator": d,
        "order_policy": policy,
    }


def dividend(
    ex="2020-01-03T08:00:00Z", pay="2020-01-04T08:00:00Z", amount="1", bps="0"
):
    return {
        "kind": "cash_dividend",
        "id": "dividend",
        "instrument": "A",
        "known_at": "2020-01-01T00:00:00Z",
        "ex_at": ex,
        "pay_at": pay,
        "amount_per_share": amount,
        "withholding_bps": bps,
    }


class CorporateTests(unittest.TestCase):
    def test_partial_order_split_sale_and_unpaid_income_reconcile_by_fraction(self):
        result = simulate_execution(control())
        cash = Fraction(1000)
        for fill in result["fills"]:
            sign = 1 if fill["side"] == "sell" else -1
            cash += sign * Fraction(fill["quantity"]) * Fraction(
                fill["price"]
            ) - Fraction(fill["fee"])
        self.assertEqual(cash, 918)
        self.assertEqual(result["cash"], {"USD": "918.00"})
        self.assertEqual(result["positions"]["A"], {"quantity": "16", "basis": "86.00"})
        self.assertEqual(Fraction(result["valuation"]["equity"]), cash + 16 * 6 + 3)
        self.assertEqual(result["valuation"]["equity"], "1017.00")
        self.assertEqual(result["orders"][0]["filled_quantity"], "20")
        self.assertEqual(
            sum(
                Fraction(row["quantity"])
                for row in result["fills"]
                if row["order_id"] == "buy"
            ),
            16,
        )
        self.assertTrue(result["ledger_audit"]["passed"])

    def test_delayed_payment_moves_receivable_to_cash_without_equity_change(self):
        value = control()
        value["ends_at"] = "2020-01-05T08:00:00Z"
        result = simulate_execution(value)
        self.assertEqual(result["cash"], {"USD": "921.00"})
        self.assertEqual(result["valuation"]["equity"], "1017.00")
        self.assertEqual(result["dividend_receivables"], {})
        self.assertEqual(result["valuation"]["dividend_receivables"], [])
        self.assertEqual(result["corporate_actions"][1]["status"], "paid")

