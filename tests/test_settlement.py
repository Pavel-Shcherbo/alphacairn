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

