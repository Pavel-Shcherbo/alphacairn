"""Hand-reconciled stresses, exact statistical controls and failed evidence cases."""

import copy
from contextlib import closing
from decimal import localcontext, Decimal, ROUND_DOWN
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from alphacairn.instruments import AccountSpec
from alphacairn.ledger import Ledger
from alphacairn.market_model import canonical, digest
from alphacairn.risk_bundle import save_risk_inputs, verify_risk_bundle, write_risk
from alphacairn.risk_engine import analyze_risk
from alphacairn.risk_history import observation_returns
from alphacairn.risk_inputs import capture_risk_inputs, prepare_risk_inputs
from alphacairn.risk_journal import capture_journal
from alphacairn.risk_matrix import (
    covariance_report,
    inverse_rank,
    matrix_diagnostics,
    sample_covariance,
)
from alphacairn.risk_model import compile_risk
from alphacairn.risk_numbers import rounded_fraction, fixed
from alphacairn.risk_tail import historical_tail

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


def resign(value):
    value["sha256"] = digest({k: v for k, v in value.items() if k != "sha256"})
    return value


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "journal.sqlite"
        self.account = load("portfolio-account.json")
        self.events = load("portfolio-events.json")
        self.ledger = Ledger(self.path, self.account)
        self.ledger.apply_batch(self.events)
        self.config = load("risk-control.json")
        self.history = load("risk-history.json")
        self.quotes = load("risk-quotes.json")

    def inputs(self):
        return capture_risk_inputs(self.path, self.config, self.history, self.quotes)

