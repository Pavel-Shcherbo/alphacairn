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

    def test_opening_only_at_first_timestamp_and_before_activity(self):
        self.ledger.apply(
            {
                "id": "cash",
                "kind": "deposit",
                "timestamp": "2020-01-01T00:00:00Z",
                "currency": "USD",
                "amount": "1",
            }
        )
        later = event()
        later["timestamp"] = "2020-01-02T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "first timestamp"):
            self.ledger.apply(later)
        self.ledger.apply(
            {
                "id": "out",
                "kind": "withdraw",
                "timestamp": "2020-01-01T00:00:00Z",
                "currency": "USD",
                "amount": "1",
            }
        )
        with self.assertRaisesRegex(ValueError, "precede activity"):
            self.ledger.apply(event())
        self.assertEqual(self.ledger.state()["positions"], {})

    def test_bad_acquisition_order_rolls_back_entire_opening_batch(self):
        with self.assertRaisesRegex(ValueError, "acquisition order"):
            self.ledger.apply_batch(
                [event("new", "2019-12-01T00:00:00Z"), event("old")]
            )
        self.assertEqual(self.ledger.state()["last_sequence"], 0)
        self.assertEqual(self.ledger.state()["lots"], [])

    def test_bad_lot_units_basis_clock_identity_and_fields_rejected(self):
        changes = [
            {"quantity": "0"},
            {"quantity": "1.1"},
            {"basis": "-1"},
            {"basis": "0.001"},
            {"basis": True},
            {"acquired_at": "2020-01-02T00:00:00Z"},
            {"acquired_at": "2019-01-01"},
            {"instrument": "missing"},
            {"source": "unknown"},
            {"id": "a" * 97},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.ledger.apply({**event(), **change})
        self.assertEqual(self.ledger.state()["last_sequence"], 0)

    def test_missing_and_future_acquisitions_rejected(self):
        value = event()
        del value["acquired_at"]
        with self.assertRaises(ValueError):
            normalize_event(value, self.ledger.spec)
        definition = control()
        definition["account"]["instruments"][0]["active_from"] = "2019-09-01T00:00:00Z"
        with self.assertRaises(ValueError):
            compile_execution(definition)

    def test_missing_mark_reports_incomplete_opening_instead_of_using_cost(self):
        value = control()
        value["initial_marks"] = []
        result = simulate_execution(value)
        self.assertFalse(result["equity_curve"][0]["complete"])
        self.assertIsNone(result["equity_curve"][0]["equity"])
        self.assertTrue(result["valuation"]["complete"])

    def test_stale_mark_is_not_current_and_future_mark_rejected(self):
        value = control()
        value["initial_marks"][0]["at"] = "2019-12-01T00:00:00Z"
        self.assertFalse(simulate_execution(value)["equity_curve"][0]["complete"])
        value["initial_marks"][0]["at"] = "2020-01-01T00:00:01Z"
        with self.assertRaisesRegex(ValueError, "future"):
            compile_execution(value)

    def test_duplicate_lots_marks_and_unheld_marks_rejected(self):
        for field in ["initial_lots", "initial_marks"]:
            value = control()
            value[field].append(copy.deepcopy(value[field][0]))
            with self.subTest(field=field), self.assertRaises(ValueError):
                compile_execution(value)
        value = control()
        value["initial_lots"] = []
        with self.assertRaisesRegex(ValueError, "held instruments"):
            compile_execution(value)

    def test_old_versions_remain_strict_and_v4_requires_explicit_opening(self):
        value = control()
        value["version"] = 3
        with self.assertRaises(ValueError):
            compile_execution(value)
        value = control()
        del value["initial_lots"]
        with self.assertRaises(ValueError):
            compile_execution(value)
        value = scenario()
        self.assertEqual(compile_execution(value).definition["version"], 1)
        self.assertNotIn("opening_holdings", simulate_execution(value))

    def test_lot_limit_and_non_list_are_rejected(self):
        for lots in [None, {}, [event()] * 1001]:
            value = control()
            value["initial_lots"] = lots
            with self.subTest(kind=type(lots).__name__), self.assertRaises(ValueError):
                compile_execution(value)

    def test_opening_split_dividend_sale_reconciles_entitlement_and_basis(self):
        value = control()
        value["commands"] = [order("sale", quantity="3", side="sell")]
        value["corporate_actions"] = [
            split(at=value["starts_at"]),
            dividend(
                ex="2020-01-02T08:00:00Z",
                pay="2020-01-03T08:00:00Z",
                amount="1",
                bps="1000",
            ),
        ]
        result = simulate_execution(value)
        self.assertEqual(result["positions"]["A"]["quantity"], "7")
        self.assertEqual(result["positions"]["A"]["basis"], "30.25")
        self.assertEqual(result["cash"], {"USD": "38.50"})
        self.assertEqual(result["corporate_actions"][1]["eligible_quantity"], "10")
        self.assertTrue(result["corporate_replay_checks"][0]["passed"])
        self.assertFalse(result["equity_curve"][0]["complete"])

    def test_opening_cannot_finance_buy_until_an_actual_sale(self):
        value = control()
        value["commands"] = [order("buy", quantity="1")]
        result = simulate_execution(value)
        self.assertEqual(result["fills"], [])
        self.assertEqual(result["positions"]["A"]["quantity"], "5")
        self.assertEqual(result["cash"], {"USD": "0.00"})

    def test_isolated_decimal_context_and_compiled_mutation_guard(self):
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.traps[Inexact] = True
            self.assertEqual(
                simulate_execution(control())["valuation"]["equity"], "53.00"
            )
        plan = compile_execution(control())
        plan.definition["initial_lots"][0]["basis"] = "0"
        with self.assertRaisesRegex(ValueError, "mutated"):
            simulate_execution(plan)

    def test_portable_bundle_replays_without_source_and_reconciles_csv(self):
        value = control()
        report = simulate_execution(value)
        directory = self.root / "bundle"
        write_execution(value, report, directory)
        value.clear()
        self.ledger.path.unlink()
        self.assertTrue(verify_execution_bundle(directory)["passed"])
        with (directory / "fills.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        cash = 0
        for row in rows:
            cents = int(Fraction(row["notional"]) * 100)
            fee = int(Fraction(row["fee"]) * 100)
            cash += (cents if row["side"] == "sell" else -cents) - fee
        self.assertEqual(cash, 500)

    def test_corrupted_acquisition_in_cache_is_detected_by_replay(self):
        self.ledger.apply(event())
        with sqlite3.connect(self.ledger.path) as db:
            db.execute("update lots set acquired_at='2019-02-01T00:00:00.000000Z'")
        db.close()
        self.assertFalse(self.ledger.audit()["passed"])

    def test_portfolio_http_evaluator_accepts_opening_and_reconciles_statement(self):
        output = evaluate_portfolio(
            {
                "mode": "portfolio",
                "account": control()["account"],
                "events": [event()],
                "quotes": {
                    "as_of": "2020-01-01T00:00:00Z",
                    "marks": {"A": {"price": "8", "timestamp": "2020-01-01T00:00:00Z"}},
                    "fx": {},
                },
                "statement": {"cash": {}, "positions": {"A": "5"}},
            }
        )
        self.assertTrue(output["passed"])
        self.assertEqual(output["valuation"]["equity"], "40.00")
        self.ledger.apply(event())
        capture = capture_journal(self.ledger.path)
        self.assertEqual(capture["events"][0]["kind"], "opening_lot")
        self.assertEqual(capture["state"]["positions"]["A"]["basis"], "40.01")

    def test_maximum_user_lot_id_reserves_generated_event_prefix(self):
        value = control()
        value["initial_lots"][0]["id"] = "a" * 80
        self.assertTrue(simulate_execution(value)["completed"])
        value["initial_lots"][0]["id"] = "a" * 81
        with self.assertRaisesRegex(ValueError, "80 characters"):
            compile_execution(value)

    def test_foreign_currency_crypto_opening_uses_explicit_fx(self):
        value = control()
        value["initial_cash"] = {}
        value["commands"] = []
        value["account"]["currencies"]["EUR"] = 2
        asset = value["account"]["instruments"][0]
        asset.update(kind="crypto_spot", quote_currency="EUR", quantity_step="0.001")
        value["initial_lots"] = [
            {
                "id": "crypto",
                "instrument": "A",
                "quantity": "0.125",
                "basis": "0.89",
                "acquired_at": "2019-01-01T00:00:00Z",
            }
        ]
        value["fx"] = [{"currency": "EUR", "at": value["starts_at"], "rate": "1.1"}]
        result = simulate_execution(value)
        self.assertEqual(result["equity_curve"][0]["equity"], "1.10")
        self.assertEqual(result["valuation"]["equity"], "1.65")
        self.assertEqual(result["positions"]["A"]["basis"], "0.89")
        value["fx"] = []
        result = simulate_execution(value)
        self.assertFalse(result["valuation"]["complete"])

    def test_empty_opening_is_supported_without_inventing_balances(self):
        value = control()
        value["initial_lots"] = []
        value["initial_marks"] = []
        value["commands"] = []
        result = simulate_execution(value)
        self.assertEqual(result["positions"], {})
        self.assertEqual(result["ledger_events"], [])
        self.assertEqual(result["opening_holdings"]["lot_count"], 0)

    def test_strategy_sizes_from_opening_inventory_and_exports_it(self):
        catalog = MarketCatalog(self.root / "market.sqlite", create=True)
        config = load("strategy-control.json")
        for name, kind in [
            ("strategy-bars.json", "bar"),
            ("strategy-universe.json", "membership"),
        ]:
            catalog.ingest(
                config["source"], kind, canonical(load(name)), request_key=kind
            )
        template = config["execution"]
        template.update(
            version=4,
            calendar=None,
            calendar_policy=None,
            price_basis="unadjusted",
            corporate_actions=[],
            initial_lots=[
                {
                    "id": "held",
                    "instrument": "STOCK-A",
                    "quantity": "3",
                    "basis": "20",
                    "acquired_at": "2019-01-01T00:00:00Z",
                }
            ],
            initial_marks=[
                {"instrument": "STOCK-A", "at": template["starts_at"], "price": "10"}
            ],
        )
        inputs = capture_strategy(catalog, config)
        result = simulate_strategy(inputs)
        self.assertEqual(result["decisions"][0]["positions_before"]["STOCK-A"], "3")
        self.assertEqual(result["decisions"][0]["actions"][0]["outcome"], "at_target")
        self.assertEqual(result["execution"]["opening_holdings"]["lot_count"], 1)
        write_strategy(inputs, result, self.root / "strategy")
        catalog.path.unlink()
        self.assertTrue(verify_strategy_bundle(self.root / "strategy")["passed"])
        changed = copy.deepcopy(config)
        changed["execution"]["initial_marks"][0]["price"] = "11"
        catalog = MarketCatalog(self.root / "other.sqlite", create=True)
        for name, kind in [
            ("strategy-bars.json", "bar"),
            ("strategy-universe.json", "membership"),
        ]:
            catalog.ingest(
                config["source"], kind, canonical(load(name)), request_key=kind
            )
        other = capture_strategy(catalog, changed)
        self.assertEqual(
            trial_contract("strategy", inputs)["recipe_sha256"],
            trial_contract("strategy", other)["recipe_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
