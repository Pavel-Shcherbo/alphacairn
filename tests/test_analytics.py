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
    pass
