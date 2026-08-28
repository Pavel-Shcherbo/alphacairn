"""Independent minor-unit, business-day and crash controls for cash settlement."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_model import compile_execution
from alphacairn.execution_export import write_execution, verify_execution_bundle
from alphacairn.instruments import AccountSpec
from alphacairn.ledger import Ledger
from alphacairn.market_model import canonical, digest
from alphacairn.market_store import MarketCatalog
from alphacairn.risk_positions import exposures, stress_portfolio
from alphacairn.risk_history import factor_exposures
from alphacairn.risk_journal import capture_journal
from alphacairn.session_model import build_calendar
from alphacairn.settlement_clock import SettlementClock
from alphacairn.settlement_service import SettlementService
from alphacairn.strategy_inputs import capture_strategy
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_bundle import write_strategy, verify_strategy_bundle
from alphacairn.study_model import trial_contract
from alphacairn.valuation import value_portfolio
from test_corporate import split, dividend
from test_strategy import load


def control():
    return load("settlement-execution.json")


def purchase(
    key="buy",
    at="2020-01-01T00:00:00Z",
    due="2020-01-03T17:00:00Z",
    side="buy",
    quantity="2",
    price="10",
    fee="1",
):
    return {
        "id": key,
        "timestamp": at,
        "kind": "trade_pending",
        "instrument": "A",
        "side": side,
        "quantity": quantity,
        "price": price,
        "fee": fee,
        "settles_at": due,
    }


def funding(amount="100"):
    return {
        "id": "fund",
        "timestamp": "2020-01-01T00:00:00Z",
        "kind": "deposit",
        "currency": "USD",
        "amount": amount,
    }


def settlement(trade="buy", key="paid", at="2020-01-03T17:00:00Z"):
    return {"id": key, "timestamp": at, "kind": "trade_settlement", "trade_id": trade}


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "journal.sqlite"
        self.ledger = Ledger(self.path, control()["account"])

    def test_joint_holiday_and_two_business_day_date_are_hand_calculated(self):
        value = control()
        clock = SettlementClock(
            value["settlement"], AccountSpec.compile(value["account"])
        )
        due = clock.due("A", "2020-01-03T09:00:00Z", "2020-01-03")
        self.assertEqual(due["settlement_date"], "2020-01-08")
        self.assertEqual(due["settles_at"], "2020-01-08T17:00:00.000000Z")
        self.assertEqual(
            clock.due("B", "2020-01-03T09:00:00Z", "2020-01-03")["settlement_date"],
            "2020-01-07",
        )

    def test_sale_cannot_finance_purchase_before_cash_is_settled(self):
        report = simulate_execution(control())
        self.assertEqual(
            [(r["instrument"], r["at"][:10]) for r in report["fills"]],
            [("A", "2020-01-03"), ("B", "2020-01-09")],
        )
        self.assertEqual(report["orders"][1]["attempts"], 4)
        self.assertEqual(report["cash"], {"USD": "5.00"})
        self.assertEqual(report["available_cash"], {"USD": "5.00"})
        self.assertEqual(
            report["positions"],
            {
                "A": {"quantity": "2", "basis": "16.00"},
                "B": {"quantity": "2", "basis": "24.50"},
            },
        )
        self.assertEqual(report["valuation"]["equity"], "49.00")
        self.assertEqual(
            report["ledger_state"]["accounts"]["USD"]["realized_income:A"], "-5.50"
        )
        points = {p["at"][:10]: p for p in report["equity_curve"]}
        self.assertEqual(points["2020-01-06"]["equity"], points["2020-01-08"]["equity"])
        self.assertEqual(points["2020-01-09"]["equity"], points["2020-01-13"]["equity"])
        self.assertEqual(
            points["2020-01-09"]["settlement_cash"],
            [
                {
                    "currency": "USD",
                    "settled": "29.50",
                    "reserved": "24.50",
                    "available": "5.00",
                }
            ],
        )
        self.assertTrue(report["ledger_audit"]["passed"])

    def test_unpaid_purchase_is_reserved_and_liability_valued_before_horizon_end(self):
        value = control()
        value["ends_at"] = "2020-01-09T17:00:00Z"
        report = simulate_execution(value)
        self.assertEqual(report["cash"], {"USD": "29.50"})
        self.assertEqual(report["available_cash"], {"USD": "5.00"})
        self.assertEqual(report["valuation"]["equity"], "49.00")
        self.assertEqual(
            report["valuation"]["trade_settlements"],
            [
                {
                    "trade_id": "simfill-000002",
                    "kind": "payable",
                    "currency": "USD",
                    "amount": "24.50",
                    "base_value": "-24.50",
                }
            ],
        )
        self.assertEqual(
            report["ledger_state"]["settlement"]["pending"][0]["settles_at"],
            "2020-01-13T17:00:00.000000Z",
        )

    def test_receivable_is_an_asset_but_not_spendable_cash(self):
        value = control()
        value["ends_at"] = "2020-01-07T17:00:00Z"
        value["bars"] = [b for b in value["bars"] if b["session"] <= "2020-01-07"]
        report = simulate_execution(value)
        self.assertEqual(report["cash"], {"USD": "0.00"})
        self.assertEqual(report["available_cash"], {"USD": "0.00"})
        self.assertEqual(report["valuation"]["equity"], "49.50")
        self.assertEqual(
            report["valuation"]["trade_settlements"][0]["kind"], "receivable"
        )
        self.assertEqual(len(report["fills"]), 1)

    def test_pending_purchase_moves_inventory_without_debiting_settled_cash(self):
        self.ledger.apply_batch([funding(), purchase()])
        state = self.ledger.state()
        self.assertEqual(state["cash"], {"USD": "100.00"})
        self.assertEqual(state["positions"]["A"], {"quantity": "2", "basis": "21.00"})
        self.assertEqual(
            state["settlement"]["cash"],
            [
                {
                    "currency": "USD",
                    "settled": "100.00",
                    "reserved": "21.00",
                    "available": "79.00",
                }
            ],
        )
        receipt = self.ledger.apply(settlement())
        self.assertEqual(self.ledger.state()["cash"], {"USD": "79.00"})
        self.assertEqual(self.ledger.apply(settlement())["duplicate"], True)
        self.assertEqual(sum(Fraction(p["amount"]) for p in receipt["postings"]), 0)
        with self.assertRaisesRegex(ValueError, "already settled"):
            self.ledger.apply(settlement(key="again"))
        self.assertTrue(self.ledger.audit()["passed"])

    def test_withdraw_fx_and_legacy_trade_cannot_spend_reserved_funds(self):
        account = control()["account"]
        account["currencies"]["EUR"] = 2
        ledger = Ledger(self.root / "other.sqlite", account)
        ledger.apply_batch([funding("21"), purchase()])
        attempts = [
            {
                "id": "withdraw",
                "timestamp": "2020-01-02T00:00:00Z",
                "kind": "withdraw",
                "currency": "USD",
                "amount": "1",
            },
            {
                "id": "fx",
                "timestamp": "2020-01-02T00:00:00Z",
                "kind": "fx",
                "from_currency": "USD",
                "to_currency": "EUR",
                "amount": "1",
                "rate": "1",
                "fee": "0",
            },
            {
                "id": "other",
                "timestamp": "2020-01-02T00:00:00Z",
                "kind": "trade",
                "instrument": "B",
                "side": "buy",
                "quantity": "1",
                "price": "1",
                "fee": "0",
            },
            purchase("another", quantity="1", price="1", fee="0"),
        ]
        for event in attempts:
            with (
                self.subTest(event=event["id"]),
                self.assertRaisesRegex(ValueError, "available cash"),
            ):
                ledger.apply(event)
        self.assertEqual(ledger.state()["last_sequence"], 2)

    def test_early_missing_conflicting_settlement_and_invalid_due_rejected(self):
        self.ledger.apply_batch([funding(), purchase()])
        for event in [
            settlement(at="2020-01-02T17:00:00Z"),
            settlement(trade="absent"),
            purchase(
                "wrong-due", at="2020-01-02T00:00:00Z", due="2020-01-01T00:00:00Z"
            ),
        ]:
            with self.assertRaises(ValueError):
                self.ledger.apply(event)
        self.assertEqual(self.ledger.state()["last_sequence"], 2)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.ledger.apply({**purchase(), "settles_at": "2020-01-04T00:00:00Z"})

    def test_settlement_can_pay_after_instrument_active_interval(self):
        account = control()["account"]
        account["instruments"][0]["active_until"] = "2020-01-02T00:00:00Z"
        ledger = Ledger(self.root / "ended.sqlite", account)
        ledger.apply_batch([funding(), purchase(), settlement()])
        self.assertEqual(ledger.state()["cash"]["USD"], "79.00")

    def test_sale_with_fee_larger_than_proceeds_reserves_the_deficit(self):
        opening = {
            "id": "opening",
            "timestamp": "2020-01-01T00:00:00Z",
            "kind": "opening_lot",
            "instrument": "A",
            "quantity": "1",
            "basis": "1",
            "acquired_at": "2019-01-01T00:00:00Z",
        }
        self.ledger.apply_batch(
            [
                funding("2"),
                opening,
                purchase("loss", side="sell", quantity="1", price="1", fee="2"),
            ]
        )
        state = self.ledger.state()
        self.assertEqual(state["settlement"]["cash"][0]["reserved"], "1.00")
        self.ledger.apply(settlement(trade="loss"))
        self.assertEqual(self.ledger.state()["cash"]["USD"], "1.00")
        self.assertEqual(
            self.ledger.state()["accounts"]["USD"]["realized_income:A"], "2.00"
        )

    def test_zero_net_sale_still_has_one_settlement_transition(self):
        buy = purchase()
        buy.update(kind="trade", quantity="1", price="1", fee="0")
        buy.pop("settles_at")
        self.ledger.apply_batch(
            [
                funding("10"),
                buy,
                purchase("zero", side="sell", quantity="1", price="1", fee="1"),
            ]
        )
        self.assertEqual(
            self.ledger.state()["settlement"]["pending"][0]["amount"], "0.00"
        )
        self.ledger.apply(settlement(trade="zero"))
        self.assertEqual(self.ledger.state()["settlement"]["pending"], [])
        self.assertTrue(self.ledger.audit()["passed"])

    def test_zero_day_rolls_after_cutoff_and_weekend_uses_joint_business_dates(self):
        value = control()
        value["settlement"]["rules"][0]["lag"] = 0
        clock = SettlementClock(
            value["settlement"], AccountSpec.compile(value["account"])
        )
        self.assertEqual(
            clock.due("A", "2020-01-03T17:00:00Z", "2020-01-03")["settlement_date"],
            "2020-01-03",
        )
        self.assertEqual(
            clock.due("A", "2020-01-03T17:00:00.000001Z", "2020-01-03")[
                "settlement_date"
            ],
            "2020-01-07",
        )
        value["settlement"]["rules"][0]["lag"] = 2
        self.assertEqual(
            SettlementClock(
                value["settlement"], AccountSpec.compile(value["account"])
            ).due("A", "2020-01-04T12:00:00Z", "2020-01-04")["settlement_date"],
            "2020-01-08",
        )

    def test_local_fill_date_and_declared_session_basis_are_distinct(self):
        value = control()
        schedule = copy.deepcopy(value["settlement"]["calendar"]["definition"])
        for row in schedule["calendars"]:
            row["timezone"] = "America/New_York"
        value["settlement"]["calendar"] = build_calendar(schedule)
        clock = SettlementClock(
            value["settlement"], AccountSpec.compile(value["account"])
        )
        self.assertEqual(
            clock.due("A", "2020-01-07T02:00:00Z", "2020-01-07")["settlement_date"],
            "2020-01-08",
        )
        value["settlement"]["rules"][0]["trade_date_basis"] = "session_label"
        self.assertEqual(
            SettlementClock(
                value["settlement"], AccountSpec.compile(value["account"])
            ).due("A", "2020-01-07T02:00:00Z", "2020-01-07")["settlement_date"],
            "2020-01-09",
        )

    def test_dst_cutoff_replays_without_host_timezone_lookup(self):
        value = control()
        schedule = value["settlement"]["calendar"]["definition"]
        schedule.update(starts_on="2020-03-05", ends_on="2020-03-13")
        for row in schedule["calendars"]:
            row.update(timezone="America/New_York", exceptions=[])
        value["settlement"]["calendar"] = build_calendar(schedule)
        value["settlement"]["rules"][0]["lag"] = 1
        with patch(
            "alphacairn.session_zones.load_zone",
            side_effect=ValueError("no host database"),
        ):
            due = SettlementClock(
                value["settlement"], AccountSpec.compile(value["account"])
            ).due("A", "2020-03-06T15:00:00Z", "2020-03-06")
        self.assertEqual(due["settles_at"], "2020-03-09T21:00:00.000000Z")

    def test_missing_rules_bad_lag_duplicate_calendar_and_corrupt_tzif_rejected(self):
        changes = [
            lambda p: p["rules"].pop(),
            lambda p: p["rules"][0].update(lag=True),
            lambda p: p["rules"][0].update(lag=11),
            lambda p: p["rules"][0].update(calendars=["usd", "usd"]),
            lambda p: p["rules"][0].update(calendars=["missing"]),
            lambda p: p["calendar"]["zones"][0].update(sha256="0" * 64),
        ]
        for change in changes:
            value = control()
            change(value["settlement"])
            with (
                self.subTest(change=changes.index(change)),
                self.assertRaises(ValueError),
            ):
                compile_execution(value)

    def test_settlement_horizon_cannot_be_silently_extrapolated(self):
        value = control()
        schedule = value["settlement"]["calendar"]["definition"]
        schedule["ends_on"] = "2020-01-07"
        value["settlement"]["calendar"] = build_calendar(schedule)
        with self.assertRaisesRegex(ValueError, "due date"):
            compile_execution(value)
        value = control()
        value["settlement"]["rules"][0]["trade_date_basis"] = "session_label"
        clock = SettlementClock(
            value["settlement"], AccountSpec.compile(value["account"])
        )
        with self.assertRaisesRegex(ValueError, "before fill"):
            clock.due("A", "2020-01-09T12:00:00Z", "2020-01-01")

    def test_overnight_business_windows_rejected_and_immediate_crypto_supported(self):
        value = control()
        schedule = value["settlement"]["calendar"]["definition"]
        for row in schedule["calendars"]:
            row["segments"][0]["open"]["time"] = "20:00"
            row["segments"][0]["close"].update(time="04:00", day_offset=1)
        value["settlement"]["calendar"] = build_calendar(schedule)
        with self.assertRaisesRegex(ValueError, "labeled local day"):
            compile_execution(value)
        value = control()
        value["settlement"] = {
            "version": 1,
            "calendar": None,
            "rules": [{"instrument": name, "mode": "immediate"} for name in ["A", "B"]],
        }
        value["account"]["instruments"][0]["kind"] = "crypto_spot"
        report = simulate_execution(value)
        self.assertEqual(
            [f["at"][:10] for f in report["fills"]], ["2020-01-03", "2020-01-03"]
        )
        self.assertEqual(report["cash"]["USD"], "5.00")
        self.assertEqual(report["available_cash"]["USD"], "5.00")
        self.assertTrue(
            all(e["status"] == "settled" for e in report["settlement"]["entries"])
        )

    def test_same_time_settlement_funds_a_new_open_before_it_is_evaluated(self):
        value = control()
        value["bars"][-1]["opened_at"] = "2020-01-09T17:00:00Z"
        value["bars"][-1]["closed_at"] = "2020-01-09T18:00:00Z"
        # Sale settles Jan 8 at 17:00; moving the last purchase open onto it tests exact equality.
        last = value["bars"].pop()
        last.update(
            session="2020-01-08",
            opened_at="2020-01-08T17:00:00Z",
            closed_at="2020-01-08T18:00:00Z",
            liquidity_known_at="2020-01-08T16:00:00Z",
        )
        value["bars"] = [
            b
            for b in value["bars"]
            if not (b["instrument"] == "B" and b["session"] == "2020-01-08")
        ] + [last]
        report = simulate_execution(value)
        self.assertEqual(report["fills"][1]["at"], "2020-01-08T17:00:00.000000Z")
        self.assertEqual(report["fills"][1]["available_cash_after"], "5.00")

    def test_batch_service_same_key_concurrent_retry_has_one_cash_transition(self):
        self.ledger.apply_batch([funding(), purchase()])
        service = SettlementService(self.path)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(
                pool.map(
                    lambda _: service.settle_due("2020-01-03T17:00:00Z", "paid-batch"),
                    range(3),
                )
            )
        self.assertTrue(all(v == results[0] for v in results))
        self.assertEqual(results[0]["settled_count"], 1)
        self.assertEqual(service.receipt("paid-batch"), results[0])
        self.assertEqual(self.ledger.state()["cash"]["USD"], "79.00")
        with self.assertRaisesRegex(ValueError, "different inputs"):
            service.settle_due("2020-01-04T17:00:00Z", "paid-batch")

    def test_batch_service_limit_retains_remaining_due_and_zero_result_retry(self):
        self.ledger.apply_batch([funding(), purchase("one"), purchase("two")])
        service = SettlementService(self.path)
        first = service.settle_due("2020-01-03T17:00:00Z", "first", limit=1)
        self.assertEqual(first["remaining_due_count"], 1)
        second = service.settle_due("2020-01-03T17:00:00Z", "second")
        self.assertEqual(second["settled_count"], 1)
        empty = service.settle_due("2020-01-03T17:00:00Z", "empty")
        self.assertEqual(empty["settled_count"], 0)
        self.assertEqual(service.settle_due("2020-01-03T17:00:00Z", "empty"), empty)
        self.assertEqual(self.ledger.state()["cash"]["USD"], "58.00")

    def test_batch_receipt_write_failure_rolls_back_cash_and_settlement_marker(self):
        self.ledger.apply_batch([funding(), purchase()])
        service = SettlementService(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(
                "CREATE TRIGGER fail_receipt BEFORE INSERT ON settlement_requests BEGIN SELECT RAISE(ABORT,'blocked receipt'); END"
            )
            db.commit()
        with self.assertRaisesRegex(sqlite3.Error, "blocked receipt"):
            service.settle_due("2020-01-03T17:00:00Z", "blocked")
        self.assertEqual(self.ledger.state()["cash"]["USD"], "100.00")
        self.assertEqual(len(self.ledger.state()["settlement"]["pending"]), 1)
        self.assertTrue(self.ledger.audit()["passed"])

    def test_killed_batch_process_leaves_no_partial_settlement(self):
        self.ledger.apply_batch([funding(), purchase()])
        script = """
import os,sys
from alphacairn.settlement_service import SettlementService
service=SettlementService(sys.argv[1]);original=service.ledger._apply
def stop(*args):
 original(*args);os._exit(17)
service.ledger._apply=stop
service.settle_due('2020-01-03T17:00:00Z','killed')
"""
        process = subprocess.run(
            [sys.executable, "-c", script, str(self.path)],
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(process.returncode, 17, process.stderr)
        service = SettlementService(self.path)
        self.assertEqual(self.ledger.state()["cash"]["USD"], "100.00")
        self.assertEqual(
            service.settle_due("2020-01-03T17:00:00Z", "killed")["settled_count"], 1
        )

    def test_pending_statement_requires_explicit_coverage_and_detects_differences(self):
        self.ledger.apply_batch([funding(), purchase()])
        statement = {"cash": {"USD": "100"}, "positions": {"A": "2"}}
        self.assertFalse(self.ledger.reconcile(statement)["matched"])
        statement["settlements"] = {
            "buy": {
                "currency": "USD",
                "kind": "payable",
                "amount": "21",
                "settles_at": "2020-01-03T17:00:00Z",
            }
        }
        self.assertTrue(self.ledger.reconcile(statement)["matched"])
        statement["settlements"]["buy"]["amount"] = "20"
        self.assertEqual(
            self.ledger.reconcile(statement)["differences"][0]["kind"], "settlements"
        )

    def test_fx_cash_and_claim_pool_has_no_rounding_gain_when_settled(self):
        account = control()["account"]
        account["currencies"]["EUR"] = 2
        account["instruments"][0]["quote_currency"] = "EUR"
        ledger = Ledger(self.root / "fx.sqlite", account)
        ledger.apply_batch(
            [
                {**funding("0.03"), "currency": "EUR"},
                purchase(quantity="1", price="0.01", fee="0"),
            ]
        )
        quotes = {"A": {"price": "0.01", "timestamp": "2020-01-03T17:00:00Z"}}
        fx = {"EUR": {"rate": "0.5", "timestamp": "2020-01-03T17:00:00Z"}}
        before = value_portfolio(
            ledger.state(), quotes, fx, as_of="2020-01-03T17:00:00Z"
        )
        ledger.apply(settlement())
        after = value_portfolio(
            ledger.state(), quotes, fx, as_of="2020-01-03T17:00:00Z"
        )
        self.assertEqual(before["equity"], after["equity"])
        self.assertEqual(before["equity"], "0.01")
        rows = exposures(ledger.state(), after, ledger.spec)
        self.assertEqual(sum(Fraction(r["base_value"]) for r in rows), Fraction("0.01"))

    def test_payable_exposures_and_joint_fx_stress_reconcile_by_fraction(self):
        account = control()["account"]
        account["currencies"]["EUR"] = 2
        account["instruments"][0]["quote_currency"] = "EUR"
        ledger = Ledger(self.root / "risk.sqlite", account)
        ledger.apply_batch([{**funding("100"), "currency": "EUR"}, purchase()])
        quotes = {
            "as_of": "2020-01-02T00:00:00Z",
            "max_age_seconds": 86400,
            "marks": {"A": {"price": "12", "timestamp": "2020-01-02T00:00:00Z"}},
            "fx": {"EUR": {"rate": "1.1", "timestamp": "2020-01-02T00:00:00Z"}},
        }
        baseline = value_portfolio(
            ledger.state(), quotes["marks"], quotes["fx"], as_of=quotes["as_of"]
        )
        rows = exposures(ledger.state(), baseline, ledger.spec)
        self.assertEqual(
            next(r["base_value"] for r in rows if r["kind"] == "trade_payable"),
            "-23.10",
        )
        factors = factor_exposures(rows, ledger.spec)
        self.assertEqual(
            next(r["base_value"] for r in factors if r["id"] == "fx:EUR"),
            Fraction("86.90"),
        )
        config = {
            "as_of": quotes["as_of"],
            "max_age_seconds": 86400,
            "scenarios": [
                {
                    "id": "joint",
                    "price_shocks": {"A": "-0.5"},
                    "fx_shocks": {"EUR": "-0.1"},
                }
            ],
        }
        result = stress_portfolio(
            ledger.state(), quotes, config, baseline, ledger.spec
        )[0]
        self.assertEqual(result["equity"], "90.09")
        self.assertEqual(
            sum(Fraction(r["pnl"]) for r in result["components"]),
            Fraction(result["pnl"]),
        )
        capture = capture_journal(ledger.path)
        self.assertEqual(
            next(
                row["available"]
                for row in capture["state"]["settlement"]["cash"]
                if row["currency"] == "EUR"
            ),
            "79.00",
        )

    def test_split_and_dividend_keep_trade_date_ownership_and_credit_spendable_cash(
        self,
    ):
        value = control()
        value["corporate_actions"] = [
            split(at="2020-01-06T08:00:00Z"),
            dividend(ex="2020-01-06T08:00:00Z", pay="2020-01-07T08:00:00Z"),
        ]
        report = simulate_execution(value)
        self.assertEqual(report["corporate_actions"][1]["eligible_quantity"], "4")
        self.assertEqual(report["cash"]["USD"], "9.00")
        self.assertEqual(report["available_cash"]["USD"], "9.00")
        self.assertTrue(report["corporate_replay_checks"][0]["passed"])

    def test_portable_execution_replays_without_original_calendar_or_journal(self):
        value = control()
        report = simulate_execution(value)
        bundle = self.root / "bundle"
        write_execution(value, report, bundle)
        value.clear()
        self.path.unlink()
        self.assertTrue(verify_execution_bundle(bundle)["passed"])
        self.assertIn("settles_at", (bundle / "fills.csv").read_text().splitlines()[0])

    def test_hostile_decimal_context_and_mutated_policy_are_rejected(self):
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.traps[Inexact] = True
            self.assertEqual(
                simulate_execution(control())["valuation"]["equity"], "49.00"
            )
        plan = compile_execution(control())
        plan.definition["settlement"]["rules"][0]["lag"] = 0
        with self.assertRaisesRegex(ValueError, "mutated"):
            simulate_execution(plan)

    def test_old_execution_contracts_reject_settlement_fields(self):
        value = control()
        value["version"] = 4
        with self.assertRaises(ValueError):
            compile_execution(value)
        value = control()
        del value["settlement"]
        with self.assertRaises(ValueError):
            compile_execution(value)

    def test_strategy_planning_and_portable_replay_keep_settlement_constraints(self):
        config = load("strategy-control.json")
        template = config["execution"]
        template.update(
            version=5,
            calendar=None,
            calendar_policy=None,
            price_basis="unadjusted",
            corporate_actions=[],
            initial_lots=[],
            initial_marks=[],
            settlement={
                "version": 1,
                "calendar": control()["settlement"]["calendar"],
                "rules": [
                    {
                        "instrument": row["id"],
                        "mode": "business_days",
                        "lag": 2,
                        "calendars": ["usd"],
                        "trade_date_basis": "local_fill_date",
                    }
                    for row in template["account"]["instruments"]
                ],
            },
        )
        catalog = MarketCatalog(self.root / "market.sqlite", create=True)
        for filename, kind in [
            ("strategy-bars.json", "bar"),
            ("strategy-universe.json", "membership"),
        ]:
            catalog.ingest(
                config["source"], kind, canonical(load(filename)), request_key=kind
            )
        inputs = capture_strategy(catalog, config)
        report = simulate_strategy(inputs)
        self.assertTrue(report["planning_replayed"])
        self.assertTrue(report["execution"]["ledger_audit"]["passed"])
        write_strategy(inputs, report, self.root / "strategy")
        catalog.path.unlink()
        self.assertTrue(verify_strategy_bundle(self.root / "strategy")["passed"])
        self.assertEqual(
            trial_contract("strategy", inputs)["recipe"]["configuration"]["execution"][
                "settlement"
            ]["rules"],
            template["settlement"]["rules"],
        )

    def test_corrupted_response_and_accepted_event_link_are_detected(self):
        self.ledger.apply_batch([funding(), purchase()])
        service = SettlementService(self.path)
        service.settle_due("2020-01-03T17:00:00Z", "receipt")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("update settlement_requests set response_sha='bad'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "receipt identity"):
            service.receipt("receipt")

    def test_partial_sale_of_unsettled_purchase_releases_fifo_without_releasing_reservation(
        self,
    ):
        self.ledger.apply_batch(
            [
                funding(),
                purchase(),
                purchase("sell", side="sell", quantity="1", price="12", fee="0"),
            ]
        )
        state = self.ledger.state()
        self.assertEqual(state["positions"]["A"]["basis"], "10.50")
        self.assertEqual(state["settlement"]["cash"][0]["available"], "79.00")
        self.assertEqual(len(state["settlement"]["pending"]), 2)
        service = SettlementService(self.path)
        result = service.settle_due("2020-01-03T17:00:00Z", "both")
        self.assertEqual(result["settled_count"], 2)
        self.assertEqual(self.ledger.state()["cash"]["USD"], "91.00")
        self.assertTrue(self.ledger.audit()["passed"])

    def test_joint_cutoff_uses_latest_utc_close_without_inferred_netting(self):
        value = control()
        schedule = value["settlement"]["calendar"]["definition"]
        schedule["calendars"][0]["segments"][0]["close"]["time"] = "19:00"
        value["settlement"]["calendar"] = build_calendar(schedule)
        due = SettlementClock(
            value["settlement"], AccountSpec.compile(value["account"])
        ).due("A", "2020-01-03T09:00:00Z", "2020-01-03")
        self.assertEqual(due["settles_at"], "2020-01-08T19:00:00.000000Z")

