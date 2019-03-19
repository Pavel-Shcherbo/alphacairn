import math
import tempfile
import unittest
from pathlib import Path

from alphacairn.backtest import load_bars, simulate


def bars(closes):
    return [
        {"date": f"2020-01-{i+1:02d}", "open": 100.0, "close": float(value)}
        for i, value in enumerate(closes)
    ]


class BacktestTests(unittest.TestCase):
    def test_current_close_cannot_change_current_trade(self):
        left = simulate(bars([100, 110, 120]), lookback=2)
        right = simulate(bars([100, 110, 1]), lookback=2)
        self.assertEqual(left["trades"], right["trades"])
        self.assertEqual(left["trades"][0]["date"], "2020-01-03")

