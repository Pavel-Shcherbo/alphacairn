import math
import statistics
import unittest
from datetime import date, timedelta

from alphacairn.analytics import (
    block_resample,
    compare,
    drawdown_history,
    period_returns,
    quantile,
    rolling_volatility,
    summarize,
)


def history(changes, initial=100):
    equity = initial
    rows = []
    for index, change in enumerate(changes):
        equity *= 1 + change
        rows.append(
            {
                "date": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
                "equity": equity,
            }
        )
    return rows


class AnalyticsTests(unittest.TestCase):
    def test_flat_returns_have_undefined_ratios_and_zero_risk(self):
        report = summarize(history([0, 0, 0]), 100)
        self.assertIsNone(report["sharpe"])
        self.assertIsNone(report["sortino"])
        self.assertEqual(report["annualized_volatility"], 0)
        self.assertEqual(report["maximum_drawdown"], 0)
        self.assertEqual(report["total_return"], 0)

    def test_fees_at_first_observation_are_not_dropped(self):
        values = [
            {"date": "2020-01-01", "equity": 99},
            {"date": "2020-01-02", "equity": 99},
        ]
        returns = period_returns(values, 100)
        self.assertAlmostEqual(returns[0], -0.01)
        self.assertEqual(returns[1], 0)
        self.assertAlmostEqual(summarize(values, 100)["total_return"], -0.01)

    def test_drawdown_episode_records_trough_and_recovery(self):
        values = [
            {"date": f"2020-01-{index+1:02d}", "equity": value}
            for index, value in enumerate([110, 100, 88, 110, 100])
        ]
        report = drawdown_history(values, 100)
        self.assertAlmostEqual(report["maximum"], 0.2)
        self.assertEqual(report["episodes"][0]["trough_date"], "2020-01-03")
        self.assertEqual(report["episodes"][0]["recovery_date"], "2020-01-04")
        self.assertEqual(report["episodes"][0]["underwater_bars"], 2)
        self.assertFalse(report["episodes"][1]["recovered"])

    def test_quantile_and_historical_tail_are_hand_checkable(self):
        self.assertEqual(quantile([0, 10], 0.25), 2.5)
        report = summarize(history([-0.1, -0.05, 0, 0.05]), 100, tail_probability=0.25)
        self.assertAlmostEqual(report["historical_var_loss"], 0.0625)
        self.assertAlmostEqual(report["historical_expected_shortfall_loss"], 0.1)

    def test_paired_comparison_recovers_known_beta(self):
        baseline = history([0.01, 0.02, -0.01, 0.03])
        strategy = history([0.02, 0.04, -0.02, 0.06])
        report = compare(strategy, baseline, 100)
        self.assertAlmostEqual(report["beta"], 2)
        self.assertAlmostEqual(report["correlation"], 1)
        self.assertAlmostEqual(report["annualized_arithmetic_alpha"], 0)
        baseline[0]["date"] = "2019-12-31"
        with self.assertRaises(ValueError):
            compare(strategy, baseline, 100)

