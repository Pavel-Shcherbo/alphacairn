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

