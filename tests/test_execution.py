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

    def test_tick_rounding_is_adverse_for_both_sides(self):
        data = scenario()
        data["initial_cash"]["USD"] = "1000"
        data["slippage_bps"] = "1"
        data["bars"] = [bar(), bar(3)]
        data["commands"] = [
            order(quantity="1"),
            order("sell", quantity="1", side="sell", at="2020-01-02T18:00:00Z"),
        ]
        result = simulate_execution(data)
        self.assertEqual([f["price"] for f in result["fills"]], ["10.01", "9.99"])
        self.assertEqual(result["cash"]["USD"], "999.98")
        self.assertEqual(result["positions"], {})

    def test_ioc_and_day_remainders_and_untouched_limit(self):
        for tif, completion in [
            ("IOC", "2020-01-02T09:00:00.000000Z"),
            ("DAY", "2020-01-02T17:00:00.000000Z"),
        ]:
            data = scenario()
            data["bars"] = [bar(liquidity="2"), bar(3)]
            data["commands"] = [order(tif=tif)]
            result = simulate_execution(data)
            self.assertEqual(len(result["fills"]), 1)
            self.assertEqual(result["orders"][0]["remaining_quantity"], "3")
            self.assertEqual(result["orders"][0]["status"], "cancelled")
            self.assertEqual(result["orders"][0]["completed_at"], completion)
        data = scenario()
        data["commands"] = [order(kind="limit", limit="1", tif="IOC")]
        self.assertEqual(simulate_execution(data)["fills"], [])

    def test_cancellation_is_effective_at_next_instrument_open(self):
        data = scenario()
        data["bars"] = [bar(liquidity="2"), bar(3)]
        data["commands"] = [
            order(),
            {
                "action": "cancel",
                "id": "cancel-buy",
                "at": "2020-01-02T18:00:00Z",
                "order_id": "buy",
            },
        ]
        result = simulate_execution(data)
        self.assertEqual(len(result["fills"]), 1)
        self.assertEqual(result["orders"][0]["status"], "cancelled")
        self.assertEqual(
            result["orders"][0]["completed_at"], "2020-01-03T09:00:00.000000Z"
        )

    def test_expiry_preempts_close_touch_and_instrument_end(self):
        data = scenario()
        data["commands"] = [
            order(kind="limit", limit="9", expires="2020-01-02T17:00:00Z")
        ]
        result = simulate_execution(data)
        self.assertEqual(result["fills"], [])
        self.assertEqual(result["orders"][0]["status"], "expired")
        data = scenario()
        data["account"]["instruments"][0]["active_until"] = "2020-01-03T00:00:00Z"
        data["bars"] = [bar(liquidity="0")]
        result = simulate_execution(data)
        self.assertEqual(result["orders"][0]["status"], "expired")

    def test_no_short_positions_or_double_selling(self):
        data = scenario()
        data["bars"] = [bar(), bar(3)]
        data["commands"] = [
            order(quantity="2"),
            order("sell-1", quantity="5", side="sell", at="2020-01-02T18:00:00Z"),
            order("sell-2", quantity="5", side="sell", at="2020-01-02T18:00:00Z"),
        ]
        result = simulate_execution(data)
        self.assertEqual([f["quantity"] for f in result["fills"]], ["2", "2"])
        self.assertEqual(result["positions"], {})
        self.assertEqual(
            result["orders"][2]["last_block_reason"], "insufficient_position"
        )

    def test_quote_currencies_do_not_implicitly_fund_each_other(self):
        data = scenario()
        data["account"]["currencies"]["EUR"] = 2
        data["account"]["instruments"].append(instrument("B", "EUR"))
        data["bars"].append(bar(name="B"))
        data["commands"] = [order(asset="B")]
        result = simulate_execution(data)
        self.assertEqual(result["fills"], [])
        self.assertEqual(result["cash"]["USD"], "100.00")
        data["initial_cash"]["EUR"] = "100"
        data["fx"] = [{"currency": "EUR", "at": "2020-01-01T00:00:00Z", "rate": "1.2"}]
        result = simulate_execution(data)
        self.assertEqual(result["cash"]["EUR"], "50.00")
        self.assertEqual(result["valuation"]["equity"], "226.00")

    def test_missing_or_stale_fx_and_marks_are_incomplete_not_zero(self):
        data = scenario()
        data["account"]["currencies"]["EUR"] = 2
        data["initial_cash"]["EUR"] = "5"
        result = simulate_execution(data)
        self.assertFalse(result["valuation"]["complete"])
        self.assertIsNone(result["valuation"]["equity"])
        data = scenario()
        data["max_mark_age_seconds"] = 0
        result = simulate_execution(data)
        self.assertFalse(result["valuation"]["complete"])
        self.assertIsNone(result["valuation"]["equity"])
        self.assertEqual(result["equity_curve"][-1]["missing_count"], 1)

    def test_fractional_step_and_fee_affordability(self):
        data = scenario()
        data["account"]["instruments"][0]["quantity_step"] = "0.25"
        data["initial_cash"]["USD"] = "10.10"
        data["fees"]["rate_bps"] = "100"
        data["commands"] = [order(quantity="2")]
        result = simulate_execution(data)
        self.assertEqual(result["fills"][0]["quantity"], "1.00")
        self.assertEqual(result["fills"][0]["fee"], "0.10")
        self.assertEqual(result["cash"]["USD"], "0.00")

    def test_future_extension_cannot_change_earlier_fills(self):
        original = scenario()
        first = simulate_execution(original)
        extended = copy.deepcopy(original)
        extended["bars"].append(bar(3, opening="20", close="22", low="18", high="25"))
        extended["commands"].append(
            order("future", quantity="1", at="2020-01-02T18:00:00Z")
        )
        second = simulate_execution(extended)
        self.assertEqual(
            first["fills"], [f for f in second["fills"] if f["at"] < "2020-01-03"]
        )

    def test_exact_context_determinism_and_compiled_plan_mutation_guard(self):
        data = scenario()
        expected = simulate_execution(data)
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            self.assertEqual(simulate_execution(data), expected)
        plan = compile_execution(data)
        plan.definition["initial_cash"]["USD"] = "999"
        with self.assertRaisesRegex(ValueError, "mutated"):
            simulate_execution(plan)

