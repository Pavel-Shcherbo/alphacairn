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

    def test_covariance_matches_hand_centered_sample(self):
        obs = [
            {"returns": [Fraction(1), Fraction(2)]},
            {"returns": [Fraction(2), Fraction(1)]},
            {"returns": [Fraction(3), Fraction(0)]},
        ]
        means, matrix = sample_covariance(obs, 2)
        self.assertEqual(means, [2, 1])
        self.assertEqual(matrix, [[1, -1], [-1, 1]])
        diagnostics = matrix_diagnostics(matrix)
        self.assertEqual(diagnostics["rank"], 1)
        self.assertIsNone(diagnostics["condition_number_one"])

    def test_negative_component_contribution_is_not_clamped(self):
        obs = [
            {"returns": [Fraction(1), Fraction(-1)]},
            {"returns": [Fraction(-1), Fraction(1)]},
        ]
        factors = [
            {"id": "one", "base_value": Fraction(1)},
            {"id": "two", "base_value": Fraction(2)},
        ]
        report = covariance_report(
            obs, factors, {"shrinkage": "0", "periods_per_year": 252}, Fraction(3)
        )
        self.assertEqual(
            [Fraction(r["variance_contribution"]) for r in report["components"]],
            [-2, 4],
        )
        self.assertEqual(Fraction(report["variance_base"]), 2)
        self.assertLess(
            Fraction(report["components"][0]["component_volatility_base"]), 0
        )

    def test_fractional_expected_shortfall_and_nearest_rank(self):
        rows = [
            {"pnl": Fraction(-i), "from": str(i), "to": str(i + 1)}
            for i in (1, 2, 3, 4)
        ]
        result = historical_tail(rows, "0.625", Fraction(100))
        self.assertEqual(Fraction(result["value_at_risk_base"]), 3)
        self.assertEqual(
            result["expected_shortfall_base_exact"],
            {"numerator": "11", "denominator": "3"},
        )
        self.assertEqual(
            [Fraction(row["observation_weight"]) for row in result["tail"]],
            [1, Fraction(1, 2)],
        )

    def test_rounding_grid_uses_half_even_for_both_signs(self):
        self.assertEqual(rounded_fraction(Fraction(5, 2), 0), 2)
        self.assertEqual(rounded_fraction(Fraction(7, 2), 0), 4)
        self.assertEqual(rounded_fraction(Fraction(-5, 2), 0), -2)
        self.assertEqual(fixed(Fraction(-7, 2), 0), "-4")

    def test_missing_history_does_not_bridge_over_the_gap(self):
        self.history["observations"][2]["prices"]["equity:demo-us"] = None
        report = analyze_risk(self.inputs())
        self.assertFalse(report["complete"])
        self.assertEqual(report["history"]["used_return_count"], 3)
        self.assertEqual(len(report["history"]["excluded_intervals"]), 2)
        self.assertEqual(
            report["statistics"]["reason"], "insufficient_complete_observations"
        )
        self.assertTrue(all(row["complete"] for row in report["stresses"]))

    def test_unavailable_revision_is_excluded_as_of(self):
        self.history["observations"][2]["available_at"] = "2026-01-03T00:00:00Z"
        report = analyze_risk(self.inputs())
        self.assertFalse(report["complete"])
        self.assertEqual(report["history"]["used_return_count"], 3)
        self.assertTrue(
            any(
                r["code"] == "not_available_as_of"
                for item in report["history"]["excluded_intervals"]
                for r in item["reasons"]
            )
        )

    def test_window_and_gap_exclusions_are_visible(self):
        self.config["history_start"] = "2025-12-28T00:00:00Z"
        report = analyze_risk(self.inputs())
        self.assertEqual(report["history"]["used_return_count"], 3)
        self.assertTrue(
            any(
                r["code"] == "outside_window"
                for item in report["history"]["excluded_intervals"]
                for r in item["reasons"]
            )
        )
        self.history["observations"] = self.history["observations"][::2]
        self.config["max_gap_days"] = 1
        report = analyze_risk(self.inputs())
        self.assertEqual(report["history"]["used_return_count"], 0)
        self.assertTrue(
            any(
                r["code"] == "observation_gap"
                for item in report["history"]["excluded_intervals"]
                for r in item["reasons"]
            )
        )

    def test_stale_baseline_blocks_estimation_and_stresses(self):
        self.quotes["marks"]["equity:demo-us"]["timestamp"] = "2025-12-01T00:00:00Z"
        report = analyze_risk(self.inputs())
        self.assertFalse(report["complete"])
        self.assertIsNone(report["valuation"]["equity"])
        self.assertFalse(report["history"]["evaluated"])
        self.assertTrue(
            all(
                not row["complete"] and row["equity"] is None
                for row in report["stresses"]
            )
        )

    def test_missing_fx_is_not_replaced_with_one(self):
        self.quotes["fx"] = {}
        report = analyze_risk(self.inputs())
        self.assertFalse(report["complete"])
        self.assertIn(
            {"kind": "fx", "currency": "EUR", "reason": "missing"},
            report["valuation"]["missing_inputs"],
        )

    def test_future_marks_and_journal_events_rejected(self):
        self.quotes["marks"]["equity:demo-us"]["timestamp"] = "2026-01-03T00:00:00Z"
        with self.assertRaises(ValueError):
            analyze_risk(self.inputs())
        self.quotes = load("risk-quotes.json")
        self.ledger.apply_batch(
            [
                {
                    "id": "later",
                    "kind": "deposit",
                    "currency": "USD",
                    "amount": "1",
                    "timestamp": "2026-01-03T00:00:00Z",
                }
            ]
        )
        with self.assertRaisesRegex(ValueError, "after the valuation"):
            analyze_risk(self.inputs())

