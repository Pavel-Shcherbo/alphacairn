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

    def test_future_test_changes_cannot_change_selected_parameter(self):
        original = bars()
        altered = [dict(row) for row in original]
        for row in altered[30:40]:
            row["close"] *= 0.5
        first = walk_forward(original, [2, 5, 10], train_size=30, test_size=10)
        changed = walk_forward(altered, [2, 5, 10], train_size=30, test_size=10)
        self.assertEqual(
            first["windows"][0]["training_scores"],
            changed["windows"][0]["training_scores"],
        )
        self.assertEqual(
            first["windows"][0]["selected_lookback"],
            changed["windows"][0]["selected_lookback"],
        )

    def test_test_windows_are_disjoint_and_cash_reconciles(self):
        report = walk_forward(bars(), [2, 5, 10], train_size=30, test_size=13)
        days = [row["date"] for row in report["equity"]]
        self.assertEqual(len(days), 50)
        self.assertEqual(len(set(days)), 50)
        for previous, current in zip(report["windows"], report["windows"][1:]):
            self.assertLess(previous["test_end"], current["test_start"])
            self.assertEqual(previous["final_cash"], current["initial_cash"])
        self.assertAlmostEqual(
            report["metrics"]["total_return"],
            report["equity"][-1]["equity"] / 10000 - 1,
        )
        self.assertGreater(report["total_fees"], 0)
        self.assertIn("not reserved", report["evaluation_policy"])

    def test_scheduled_exit_includes_sell_cost(self):
        values = [
            {"date": "2020-01-01", "open": 100, "close": 100},
            {"date": "2020-01-02", "open": 100, "close": 100},
        ]
        report = simulate(
            values,
            buy_and_hold=True,
            fee_bps=100,
            slippage_bps=0,
            liquidate_at_end=True,
        )
        self.assertAlmostEqual(report["final_equity"], 10000 / 1.01 * 0.99)
        self.assertEqual(report["trades"][-1]["reason"], "scheduled_window_exit")
        self.assertEqual(report["trades"][-1]["execution_point"], "close")

    def test_oversized_candidate_workload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            walk_forward(bars(3000), list(range(2, 102)), train_size=1000, test_size=1)

    def test_invalid_windows_are_rejected(self):
        for params in [{"train_size": 10}, {"test_size": 0}, {"score": "unknown"}]:
            with self.assertRaises(ValueError):
                walk_forward(bars(), [2, 5, 10], **params)
