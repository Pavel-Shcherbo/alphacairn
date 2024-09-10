"""Frozen attempts, selection discipline, access history and independent replay."""

import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import concurrent.futures
import subprocess
import sys

from alphacairn.instruments import timestamp, timestamp_text
from alphacairn.ledger import Ledger
from alphacairn.market_model import digest, canonical
from alphacairn.market_store import MarketCatalog
from alphacairn.risk_inputs import capture_risk_inputs
from alphacairn.study_model import declaration
from alphacairn.study_store import StudyRegistry
from alphacairn.study_runner import run_trial
from alphacairn.study_evidence import (
    audit_study,
    export_trial,
    verify_study_export,
    compare_trials,
)
from alphacairn.strategy_inputs import capture_strategy

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


def resign(value):
    value["sha256"] = digest({k: v for k, v in value.items() if k != "sha256"})
    return value


def holdout(inputs):
    result = copy.deepcopy(inputs)
    shift = lambda value: timestamp_text(timestamp(value) + timedelta(days=31))
    for key in ("as_of", "history_start", "history_end"):
        result["configuration"][key] = shift(result["configuration"][key])
    result["quotes"]["as_of"] = shift(result["quotes"]["as_of"])
    for quote in list(result["quotes"]["marks"].values()) + list(
        result["quotes"]["fx"].values()
    ):
        quote["timestamp"] = shift(quote["timestamp"])
    for point in result["history"]["observations"]:
        point["at"] = shift(point["at"])
        point["available_at"] = shift(point["available_at"])
    return resign(result)


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        ledger = Ledger(self.root / "ledger.sqlite", load("portfolio-account.json"))
        ledger.apply_batch(load("portfolio-events.json"))
        self.inputs = capture_risk_inputs(
            ledger.path,
            load("risk-control.json"),
            load("risk-history.json"),
            load("risk-quotes.json"),
        )
        self.registry = StudyRegistry(self.root / "studies.sqlite")
        self.plan = {
            "version": 1,
            "name": "synthetic-risk-review",
            "family": "risk",
            "hypothesis": "Review a fixed covariance estimator without omitting failed inputs.",
            "development": {
                "start": "2025-12-01T00:00:00Z",
                "end": "2026-01-03T00:00:00Z",
            },
            "holdout": {"start": "2026-01-25T00:00:00Z", "end": "2026-02-03T00:00:00Z"},
        }
        self.study = self.registry.create("project", self.plan)["id"]

