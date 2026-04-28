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

