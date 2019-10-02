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
        self.assertEqual(
            short["trades"],
            [trade for trade in long["trades"] if trade["date"] <= "2020-01-04"],
        )
        for trade in long["trades"]:
            if trade["signal_date"] is not None:
                self.assertLess(trade["signal_date"], trade["date"])

    def test_flat_market_costs_and_drawdown(self):
        free = simulate(bars([100, 100]), fee_bps=0, slippage_bps=0, buy_and_hold=True)
        paid = simulate(
            bars([100, 100]), fee_bps=100, slippage_bps=0, buy_and_hold=True
        )
        self.assertEqual(free["total_return"], 0)
        self.assertAlmostEqual(paid["final_equity"], 10000 / 1.01)
        loss = simulate(bars([100, 50]), fee_bps=0, slippage_bps=0, buy_and_hold=True)
        self.assertEqual(loss["max_drawdown"], 0.5)

    def test_reject_invalid_prices_dates_and_costs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bars.csv"
            for content in [
                "date,open,close\n2020-01-01,nan,10\n2020-01-02,1,2",
                "date,open,close\n2020-01-02,1,2\n2020-01-01,1,2",
            ]:
                path.write_text(content)
                with self.assertRaises(ValueError):
                    load_bars(path)
        for cost in [math.nan, -1, 10000]:
            with self.assertRaises(ValueError):
                simulate(bars([100, 100]), fee_bps=cost)
