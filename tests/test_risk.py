"""Hand-reconciled stresses, exact statistical controls and failed evidence cases."""

import copy
from contextlib import closing
from decimal import localcontext, Decimal, ROUND_DOWN
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from alphacairn.instruments import AccountSpec
from alphacairn.ledger import Ledger
from alphacairn.market_model import canonical, digest
from alphacairn.risk_bundle import save_risk_inputs, verify_risk_bundle, write_risk
from alphacairn.risk_engine import analyze_risk
from alphacairn.risk_history import observation_returns
from alphacairn.risk_inputs import capture_risk_inputs, prepare_risk_inputs
from alphacairn.risk_journal import capture_journal
from alphacairn.risk_matrix import (
    covariance_report,
    inverse_rank,
    matrix_diagnostics,
    sample_covariance,
)
from alphacairn.risk_model import compile_risk
from alphacairn.risk_numbers import rounded_fraction, fixed
from alphacairn.risk_tail import historical_tail

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


def resign(value):
    value["sha256"] = digest({k: v for k, v in value.items() if k != "sha256"})
    return value


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "journal.sqlite"
        self.account = load("portfolio-account.json")
        self.events = load("portfolio-events.json")
        self.ledger = Ledger(self.path, self.account)
        self.ledger.apply_batch(self.events)
        self.config = load("risk-control.json")
        self.history = load("risk-history.json")
        self.quotes = load("risk-quotes.json")

    def inputs(self):
        return capture_risk_inputs(self.path, self.config, self.history, self.quotes)

    def test_current_values_and_independent_stress_integer_cents(self):
        report = analyze_risk(self.inputs())
        self.assertTrue(report["complete"])
        self.assertEqual(report["valuation"]["equity"], "10948.90")
        self.assertEqual(
            sum(Fraction(row["base_value"]) for row in report["exposures"]),
            Fraction(109489, 10),
        )
        scenario = report["stresses"][1]
        # USD cash 720000c + US 36000c + EU 53460c + crypto 110000c + EUR cash 39501c.
        independently_valued_cents = 720000 + 36000 + 53460 + 110000 + 39501
        self.assertEqual(Fraction(scenario["equity"]) * 100, independently_valued_cents)
        self.assertEqual(Fraction(scenario["pnl"]) * 100, -135929)
        self.assertEqual(Fraction(report["stresses"][0]["pnl"]), 0)
        self.assertEqual(Fraction(report["stresses"][2]["pnl"]), Fraction(-10989, 100))

    def test_complete_history_and_rank_shrinkage_are_explicit(self):
        report = analyze_risk(self.inputs())
        cov = report["statistics"]["covariance"]
        self.assertEqual(report["history"]["used_return_count"], 5)
        self.assertEqual(cov["sample_diagnostics"]["rank"], 1)
        self.assertTrue(cov["sample_diagnostics"]["singular"])
        self.assertEqual(cov["regularized_diagnostics"]["rank"], 4)
        self.assertFalse(
            cov["regularized_diagnostics"]["inverse_used_for_portfolio_risk"]
        )
        self.assertIn({"code": "sample_covariance_singular"}, report["warnings"])

    def test_static_historical_shocks_have_independent_signed_pnl(self):
        report = analyze_risk(self.inputs())
        pnls = [Fraction(row["pnl"]) for row in report["history"]["intervals"]]
        self.assertEqual(
            pnls,
            [
                Fraction(749, 100),
                Fraction(571, 100),
                Fraction(749, 100),
                Fraction(571, 100),
                Fraction(749, 100),
            ],
        )
        tail = report["statistics"]["historical_tail"]
        self.assertEqual(Fraction(tail["value_at_risk_base"]), Fraction(-571, 100))
        self.assertEqual(Fraction(tail["expected_shortfall_base"]), Fraction(-571, 100))
        self.assertEqual(Fraction(tail["tail_observation_mass"]), Fraction(1, 4))

