"""Independent cash controls and adversarial decision-versus-execution clocks."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal, Inexact, localcontext
from pathlib import Path

from alphacairn.execution_export import json_data
from alphacairn.market_model import canonical, digest, snapshot_identity
from alphacairn.market_store import MarketCatalog
from alphacairn.strategy_bundle import (
    verify_strategy_bundle,
    write_strategy,
    write_strategy_inputs,
)
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_inputs import (
    capture_strategy,
    compile_strategy,
    prepare_strategy_inputs,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


def rehash_inputs(document):
    document["sha256"] = digest(
        {key: value for key, value in document.items() if key != "sha256"}
    )


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = MarketCatalog(self.root / "market.sqlite", create=True)
        self.definition = load("strategy-control.json")
        self.bars = load("strategy-bars.json")
        self.members = load("strategy-universe.json")
        self.ingest(self.bars, "bar", "bars")
        self.ingest(self.members, "membership", "members")

    def ingest(self, rows, kind="bar", key="revision"):
        return self.catalog.ingest(
            self.definition["source"], kind, canonical(rows), request_key=key
        )

    def run_study(self, definition=None):
        inputs = capture_strategy(self.catalog, definition or self.definition)
        return inputs, simulate_strategy(inputs)

