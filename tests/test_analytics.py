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

