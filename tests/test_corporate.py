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

    def test_sale_after_ex_retains_income_until_payment(self):
        value = simple([dividend(pay="2020-01-05T08:00:00Z")])
        value["bars"] = [bar(2), bar(3), bar(4)]
        value["commands"].append(
            order("sell", side="sell", quantity="5", at="2020-01-03T08:00:00Z")
        )
        result = simulate_execution(value)
        self.assertEqual(result["positions"], {})
        self.assertEqual(result["cash"], {"USD": "100.00"})
        self.assertEqual(result["valuation"]["equity"], "105.00")
        self.assertEqual(result["corporate_actions"][0]["eligible_quantity"], "5")

    def test_ex_before_same_open_excludes_new_buyer(self):
        value = simple([dividend(ex="2020-01-02T09:00:00Z")])
        result = simulate_execution(value)
        self.assertEqual(result["corporate_actions"][0]["eligible_quantity"], "0")
        self.assertEqual(
            result["corporate_actions"][0]["status"], "no_cash_entitlement"
        )
        self.assertEqual(result["cash"], {"USD": "50.00"})

    def test_split_before_same_instant_dividend_uses_new_units(self):
        result = simulate_execution(control())
        self.assertEqual(result["corporate_actions"][1]["eligible_quantity"], "8")
        self.assertEqual(result["corporate_actions"][1]["gross"], "4.00")
        self.assertEqual(result["corporate_actions"][1]["withholding"], "1.00")

    def test_split_cancels_live_order_under_explicit_policy(self):
        value = control()
        value["corporate_actions"][0]["order_policy"] = "cancel"
        result = simulate_execution(value)
        self.assertEqual(result["orders"][0]["status"], "cancelled")
        self.assertEqual(result["orders"][0]["corporate_adjustments"], [])
        self.assertEqual(
            result["corporate_actions"][0]["order_adjustments"][0]["policy"], "cancel"
        )

    def test_future_submission_is_already_in_its_declared_units(self):
        value = simple([split()])
        value["bars"] = [bar(2), bar(3, opening="5", close="5", low="5")]
        value["commands"] = [order(at="2020-01-03T08:00:00Z", quantity="3")]
        result = simulate_execution(value)
        self.assertEqual(result["positions"]["A"]["quantity"], "3")
        self.assertEqual(result["orders"][0]["corporate_adjustments"], [])

    def test_limit_adjustment_is_exact_and_original_definition_preserved(self):
        value = control()
        value["commands"][0].update(kind="limit", limit="10")
        original = copy.deepcopy(value)
        result = simulate_execution(value)
        self.assertEqual(value, original)
        order = result["orders"][0]
        self.assertEqual(order["limit"], "5")
        self.assertEqual(order["original_definition"]["limit"], "10")
        self.assertEqual(order["original_definition"]["quantity"], "10")
        self.assertEqual(order["corporate_adjustments"][0]["remaining_after"], "12")

    def test_unrepresentable_order_limit_rejected_without_rounding(self):
        value = control()
        value["commands"][0].update(kind="limit", limit="10.01")
        with self.assertRaisesRegex(ValueError, "increment"):
            simulate_execution(value)

    def test_reverse_split_fractional_lot_rejected(self):
        value = simple([split(n=1, d=2)])
        value["commands"][0]["quantity"] = "5"
        with self.assertRaisesRegex(ValueError, "increment"):
            simulate_execution(value)

    def test_each_fifo_lot_must_survive_reverse_split_not_only_total(self):
        value = simple([split(n=1, d=2)])
        value["commands"] = [order(quantity="1"), order("second", quantity="1")]
        with self.assertRaisesRegex(ValueError, "post-split lot"):
            simulate_execution(value)

    def test_split_invalidates_old_mark_instead_of_doubling_equity(self):
        value = simple([split(at="2020-01-04T17:00:00Z")])
        result = simulate_execution(value)
        self.assertFalse(result["valuation"]["complete"])
        self.assertIsNone(result["valuation"]["equity"])
        self.assertEqual(
            result["equity_curve"][-1]["missing_sample"][0]["kind"], "mark"
        )

    def test_dividend_ex_invalidates_old_cum_dividend_mark(self):
        value = simple(
            [dividend(ex="2020-01-04T17:00:00Z", pay="2020-01-05T08:00:00Z")]
        )
        result = simulate_execution(value)
        self.assertFalse(result["valuation"]["complete"])
        self.assertIsNone(result["valuation"]["equity"])
        self.assertEqual(result["valuation"]["known_base_value"], "55.00")
        self.assertEqual(
            result["valuation"]["dividend_receivables"][0]["amount"], "5.00"
        )

    def test_action_inside_daily_bar_or_unknown_clock_rejected(self):
        for action in (
            split(at="2020-01-02T12:00:00Z"),
            dividend(ex="2020-01-02T12:00:00Z"),
            {**split(), "known_at": "2020-01-04T00:00:00Z"},
        ):
            with self.assertRaises(ValueError):
                compile_execution(simple([action]))

    def test_strict_action_contract_and_adjusted_prices_rejected(self):
        cases = [
            {**split(), "numerator": True},
            {**split(), "denominator": 0},
            {**split(), "order_policy": "round"},
            {**dividend(), "withholding_bps": "10001"},
            {**dividend(), "pay_at": "2020-01-02T00:00:00Z"},
        ]
        for item in cases:
            with self.assertRaises(ValueError):
                compile_execution(simple([item]))
        value = simple([split(), split()])
        with self.assertRaises(ValueError):
            compile_execution(value)
        value = simple([])
        value["price_basis"] = "split_adjusted"
        with self.assertRaisesRegex(ValueError, "unadjusted"):
            compile_execution(value)
        value = simple([split()])
        value["account"]["instruments"][0]["kind"] = "crypto_spot"
        with self.assertRaisesRegex(ValueError, "equity"):
            compile_execution(value)

    def test_full_withholding_zero_net_and_duplicate_payment_protection(self):
        value = simple([dividend(bps="10000")])
        result = simulate_execution(value)
        self.assertEqual(result["cash"], {"USD": "50.00"})
        self.assertEqual(result["dividend_receivables"], {})
        with tempfile.TemporaryDirectory() as root:
            ledger = Ledger(Path(root) / "ledger.sqlite", value["account"])
            ledger.apply_batch(result["ledger_events"])
            paid = next(
                event
                for event in result["ledger_events"]
                if event["kind"] == "dividend_payment"
            )
            self.assertTrue(ledger.apply(paid)["duplicate"])
            with self.assertRaisesRegex(ValueError, "already been paid"):
                ledger.apply({**paid, "id": "another-payment"})
            self.assertTrue(ledger.audit()["passed"])

    def test_receivable_cannot_fund_purchase_until_pay_time(self):
        value = simple([dividend(amount="10", pay="2020-01-04T08:00:00Z")])
        value["initial_cash"] = {"USD": "50"}
        value["bars"] = [bar(2), bar(3), bar(4)]
        value["commands"].append(
            order("additional", quantity="5", at="2020-01-03T08:00:00Z")
        )
        result = simulate_execution(value)
        added = [fill for fill in result["fills"] if fill["order_id"] == "additional"]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["session"], "2020-01-04")

    def test_foreign_currency_receivable_requires_fx_after_position_sale(self):
        value = simple([dividend(pay="2020-01-05T00:00:00Z")])
        value["account"]["currencies"]["EUR"] = 2
        value["account"]["instruments"][0]["quote_currency"] = "EUR"
        value["initial_cash"] = {"USD": "0", "EUR": "100"}
        value["bars"] = [bar(2), bar(3)]
        value["commands"].append(
            order("sell", side="sell", quantity="5", at="2020-01-03T08:00:00Z")
        )
        result = simulate_execution(value)
        self.assertFalse(result["valuation"]["complete"])
        self.assertTrue(
            any(item["kind"] == "fx" for item in result["valuation"]["missing_inputs"])
        )
        value["fx"] = [{"currency": "EUR", "at": "2020-01-01T00:00:00Z", "rate": "1.2"}]
        result = simulate_execution(value)
        self.assertEqual(result["valuation"]["equity"], "126.00")

    def test_ledger_accrual_and_payment_balanced_replay_and_reopen(self):
        value = simple([])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "ledger.sqlite"
            ledger = Ledger(path, value["account"])
            accrual = {
                "id": "claim",
                "kind": "dividend_accrual",
                "timestamp": "2020-01-01T00:00:00Z",
                "instrument": "A",
                "gross": "10",
                "withholding": "2",
            }
            ledger.apply(accrual)
            state = ledger.state()
            valuation = value_portfolio(state, {}, {}, as_of="2020-01-01T00:00:00Z")
            self.assertEqual(valuation["equity"], "8.00")
            self.assertEqual(state["cash"], {})
            reopened = Ledger(path)
            reopened.apply(
                {
                    "id": "paid",
                    "kind": "dividend_payment",
                    "timestamp": "2020-01-02T00:00:00Z",
                    "accrual_id": "claim",
                }
            )
            self.assertEqual(reopened.state()["cash"], {"USD": "8.00"})
            self.assertTrue(reopened.audit()["passed"])
            with self.assertRaises(ValueError):
                reopened.apply(
                    {
                        "id": "bad",
                        "kind": "dividend_payment",
                        "timestamp": "2020-01-03T00:00:00Z",
                        "accrual_id": "missing",
                    }
                )

    def test_exact_split_signal_factors_have_no_future_action_leak(self):
        rows = [
            {"observation": {"close": "10", "closed_at": "2020-01-02T17:00:00Z"}},
            {"observation": {"close": "6", "closed_at": "2020-01-03T17:00:00Z"}},
        ]
        action = split()
        prices, used = signal_prices(
            [action], "A", rows, {"at": "2020-01-03T18:00:00Z"}
        )
        self.assertEqual(prices, [Fraction(5), Fraction(6)])
        self.assertEqual(used, ["split"])
        prices, used = signal_prices(
            [action], "A", rows[:1], {"at": "2020-01-02T18:00:00Z"}
        )
        self.assertEqual(prices, [Fraction(10)])
        self.assertEqual(used, [])

    def test_strategy_actions_use_same_book_and_portable_bundle_replay(self):
        config = load("strategy-control.json")
        bars = load("strategy-bars.json")
        config["execution"].update(
            version=3,
            calendar=None,
            calendar_policy=None,
            price_basis="unadjusted",
            corporate_actions=[
                {**split(), "instrument": "STOCK-A", "order_policy": "cancel"},
                {**dividend(amount="0.50"), "instrument": "STOCK-A"},
            ],
        )
        with tempfile.TemporaryDirectory() as root:
            catalog = MarketCatalog(Path(root) / "market.sqlite", create=True)
            for kind, records in [
                ("bar", bars),
                ("membership", load("strategy-universe.json")),
            ]:
                catalog.ingest(
                    config["source"], kind, canonical(records), request_key=kind
                )
            inputs = capture_strategy(catalog, config)
            report = simulate_strategy(inputs)
            self.assertTrue(report["planning_replayed"])
            self.assertTrue(report["execution"]["ledger_audit"]["passed"])
            feature = next(
                item
                for item in report["windows"][1]["features"]
                if item["instrument"] == "STOCK-A"
            )
            self.assertIn("split", feature["split_actions"])
            write_strategy(inputs, report, Path(root) / "bundle")
            self.assertTrue(verify_strategy_bundle(Path(root) / "bundle")["passed"])

    def test_execution_export_replays_actions_and_detects_modified_report(self):
        value = control()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bundle"
            write_execution(value, simulate_execution(value), path)
            self.assertTrue(verify_execution_bundle(path)["passed"])
            report = json.loads((path / "report.json").read_text())
            report["corporate_actions"][1]["eligible_quantity"] = "999"
            (path / "report.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                verify_execution_bundle(path)

    def test_dividend_replay_independently_checks_share_ownership(self):
        from unittest.mock import patch
        from alphacairn.corporate_book import CorporateBook

        original = CorporateBook.ex

        def wrong(self, action, at):
            original(self, action, at)
            self.entitlements[action["id"]]["eligible_quantity"] = "999"

        with patch.object(CorporateBook, "ex", wrong):
            with self.assertRaisesRegex(RuntimeError, "independent journal ownership"):
                simulate_execution(control())

    def test_v3_can_use_retained_calendar_and_accrued_dividend(self):
        from alphacairn.session_model import build_calendar
        from test_sessions import schedule

        value = simple([dividend()])
        value["bars"] = [bar(2), bar(3)]
        value["ends_at"] = "2020-01-04T00:00:00Z"
        value["calendar"] = build_calendar(schedule())
        value["calendar_policy"] = {"require_all_sessions": True}
        result = simulate_execution(value)
        self.assertTrue(result["calendar_validation"]["complete"])
        self.assertTrue(result["corporate_replay_checks"][0]["passed"])

    def test_decimal_context_and_caller_input_remain_unchanged(self):
        value = control()
        original = copy.deepcopy(value)
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            result = simulate_execution(value)
        self.assertEqual(value, original)
        self.assertEqual(result["valuation"]["equity"], "1017.00")

