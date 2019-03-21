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

    def test_future_extension_does_not_change_past(self):
        short = simulate(bars([100, 110, 120, 90]), lookback=2)
        long = simulate(bars([100, 110, 120, 90, 80, 200]), lookback=2)
        self.assertEqual(short["equity"], long["equity"][:4])

    def test_flat_market_costs_and_drawdown(self):
        free = simulate(bars([100, 100]), fee_bps=0, slippage_bps=0, buy_and_hold=True)
        paid = simulate(
            bars([100, 100]), fee_bps=100, slippage_bps=0, buy_and_hold=True
        )
        self.assertEqual(free["total_return"], 0)
        self.assertAlmostEqual(paid["final_equity"], 10000 / 1.01)
        loss = simulate(bars([100, 50]), fee_bps=0, slippage_bps=0, buy_and_hold=True)
        self.assertEqual(loss["max_drawdown"], 0.5)

