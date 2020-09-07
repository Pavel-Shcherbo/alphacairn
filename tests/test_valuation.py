import tempfile
import unittest
from pathlib import Path

from alphacairn.ledger import Ledger
from alphacairn.valuation import value_portfolio
from portfolio_fixtures import account_spec, scenario_events

AS_OF = "2026-01-02T16:00:00Z"


