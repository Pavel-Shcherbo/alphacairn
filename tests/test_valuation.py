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

