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
    pass
