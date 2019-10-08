import unittest
from datetime import date, timedelta

from alphacairn.backtest import simulate
from alphacairn.walkforward import walk_forward


def bars(count=80):
    result = []
    price = 100.0
    for index in range(count):
        close = price * (1.01 if index % 7 < 4 else 0.985)
        result.append(
            {
                "date": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
                "open": price,
                "close": close,
            }
        )
        price = close
    return result


class WalkForwardTests(unittest.TestCase):
    def test_warmup_observes_prices_without_trading(self):
        report = simulate(bars(8), lookback=2, trade_from=5, liquidate_at_end=True)
        self.assertTrue(all(row["equity"] == 10000 for row in report["equity"][:5]))
        self.assertTrue(
            all(trade["date"] >= "2020-01-06" for trade in report["trades"])
        )
        self.assertEqual(report["equity"][-1]["quantity"], 0)

