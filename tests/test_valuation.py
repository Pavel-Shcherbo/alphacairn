import tempfile
import unittest
from pathlib import Path

from alphacairn.ledger import Ledger
from alphacairn.valuation import value_portfolio
from portfolio_fixtures import account_spec, scenario_events

AS_OF = "2026-01-02T16:00:00Z"


def marks():
    return {
        name: {"price": price, "timestamp": AS_OF}
        for name, price in [
            ("equity:demo-us", "75"),
            ("equity:demo-eu", "60"),
            ("crypto:demo", "22000"),
        ]
    }


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        ledger = Ledger(Path(self.temporary.name) / "ledger.sqlite", account_spec())
        ledger.apply_batch(scenario_events())
        self.state = ledger.state()
        self.fx = {"EUR": {"rate": "1.1", "timestamp": AS_OF}}

    def value(self, prices=None, fx=None, **options):
        return value_portfolio(
            self.state,
            marks() if prices is None else prices,
            self.fx if fx is None else fx,
            as_of=options.pop("as_of", AS_OF),
            **options,
        )

    def test_multi_currency_equity_matches_hand_calculation(self):
        result = self.value()
        self.assertTrue(result["complete"])
        self.assertEqual(result["equity"], "10948.90")
        positions = {item["instrument"]: item for item in result["positions"]}
        self.assertEqual(positions["equity:demo-us"]["unrealized_quote_pnl"], "89.40")
        self.assertEqual(positions["crypto:demo"]["market_value"], "2200.00")
        self.assertEqual(positions["equity:demo-eu"]["base_value"], "660.00")

    def test_missing_or_stale_prices_never_become_zero_equity(self):
        prices = marks()
        prices.pop("crypto:demo")
        missing = self.value(prices)
        self.assertFalse(missing["complete"])
        self.assertIsNone(missing["equity"])
        self.assertEqual(missing["known_base_value"], "8748.90")
        prices = marks()
        prices["crypto:demo"]["timestamp"] = "2025-12-01T00:00:00Z"
        stale = self.value(prices)
        self.assertIn(
            {"kind": "mark", "instrument": "crypto:demo", "reason": "stale"},
            stale["missing_inputs"],
        )

    def test_missing_fx_is_deduplicated_across_cash_and_positions(self):
        result = self.value(fx={})
        self.assertIsNone(result["equity"])
        self.assertEqual(
            result["missing_inputs"],
            [{"currency": "EUR", "kind": "fx", "reason": "missing"}],
        )

    def test_zero_price_is_a_valid_explicit_total_loss_mark(self):
        prices = marks()
        prices["crypto:demo"]["price"] = "0"
        result = self.value(prices)
        self.assertTrue(result["complete"])
        self.assertEqual(result["equity"], "8748.90")

    def test_future_marks_and_historical_state_mismatch_are_rejected(self):
        prices = marks()
        prices["crypto:demo"]["timestamp"] = "2026-01-03T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "after"):
            self.value(prices)
        with self.assertRaisesRegex(ValueError, "historical"):
            self.value(as_of="2026-01-01T00:00:00Z")

