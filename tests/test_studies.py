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

    def register(self, inputs=None, key="one", partition="development"):
        return self.registry.register(
            "project",
            self.study,
            inputs or self.inputs,
            partition,
            key,
            "Synthetic " + key,
        )

    def execute(self, trial):
        return run_trial(
            self.registry,
            "project",
            trial["id"],
            actor="reviewer",
            reason="Execute declared frozen control",
        )

    def select(self, trial):
        return self.registry.select(
            "project",
            self.study,
            trial["id"],
            actor="reviewer",
            reason="Select complete frozen baseline",
        )

    def test_declaration_idempotence_and_scope(self):
        self.assertEqual(self.registry.create("project", self.plan)["id"], self.study)
        changed = copy.deepcopy(self.plan)
        changed["hypothesis"] = "Another hypothesis"
        with self.assertRaises(ValueError):
            self.registry.create("project", changed)
        with self.assertRaises(ValueError):
            self.registry.overview("other", self.study)
        trial = self.register()
        with self.assertRaises(ValueError):
            self.registry.read("other", trial["id"], actor="a", reason="b")

    def test_register_retry_and_input_binding(self):
        first = self.register()
        self.assertEqual(first, self.register())
        self.assertEqual(first["input_sha256"], self.inputs["sha256"])
        changed = copy.deepcopy(self.inputs)
        changed["configuration"]["shrinkage"] = "0.2"
        resign(changed)
        with self.assertRaises(ValueError):
            self.register(changed)
        self.assertEqual(
            self.registry.overview("project", self.study)["registered_trial_count"], 1
        )

    def test_success_incomplete_and_failed_attempts_are_all_retained(self):
        good = self.register(key="good")
        incomplete = copy.deepcopy(self.inputs)
        incomplete["history"]["observations"] = incomplete["history"]["observations"][
            :2
        ]
        resign(incomplete)
        partial = self.register(incomplete, "incomplete")
        failed = copy.deepcopy(self.inputs)
        failed["quotes"]["marks"]["crypto:demo"]["timestamp"] = "2026-01-03T00:00:00Z"
        resign(failed)
        broken = self.register(failed, "failed")
        self.assertEqual(
            [self.execute(t)["record"]["status"] for t in (good, partial, broken)],
            ["succeeded", "incomplete", "failed"],
        )
        overview = self.registry.overview("project", self.study)
        self.assertEqual(overview["registered_trial_count"], 3)
        self.assertEqual(overview["failed_trial_count"], 2)
        self.assertEqual(overview["holdout_access_attempts"], 0)
        self.assertTrue(audit_study(self.registry, "project", self.study)[2]["passed"])
        for trial in (good, partial, broken):
            self.assertTrue(
                verify_study_export(
                    export_trial(
                        self.registry,
                        "project",
                        trial["id"],
                        actor="reviewer",
                        reason="Independent replay",
                    )
                )["passed"]
            )

    def test_pending_attempt_blocks_selection_and_cannot_be_hidden(self):
        good = self.register()
        self.execute(good)
        pending = self.register(key="pending")
        with self.assertRaises(ValueError):
            self.select(good)
        self.execute(pending)
        self.select(good)
        self.assertEqual(
            self.registry.overview("project", self.study)["selection"]["trial"],
            good["id"],
        )
        with self.assertRaises(ValueError):
            self.register(key="late")
        with self.assertRaises(ValueError):
            self.select(good)

    def test_holdout_requires_selection_and_same_method(self):
        with self.assertRaises(ValueError):
            self.register(holdout(self.inputs), "holdout", "holdout")
        good = self.register()
        self.execute(good)
        self.select(good)
        changed = holdout(self.inputs)
        changed["configuration"]["shrinkage"] = "0.3"
        resign(changed)
        with self.assertRaises(ValueError):
            self.register(changed, "changed", "holdout")
        trial = self.register(holdout(self.inputs), "holdout", "holdout")
        self.assertEqual(trial["partition"], "holdout")

    def test_holdout_registration_is_not_claimed_as_external_blindness(self):
        good = self.register()
        self.execute(good)
        self.select(good)
        trial = self.register(holdout(self.inputs), "holdout", "holdout")
        before = self.registry.overview("project", self.study)
        self.assertTrue(before["holdout_registry_unopened"])
        self.assertEqual(before["holdout_access_attempts"], 0)
        self.registry.read(
            "project",
            trial["id"],
            actor="reviewer",
            reason="Open captured holdout inputs",
        )
        self.execute(trial)
        self.execute(trial)
        self.registry.read(
            "project", trial["id"], actor="reviewer", reason="Read result again"
        )
        document = export_trial(
            self.registry,
            "project",
            trial["id"],
            actor="reviewer",
            reason="Share review evidence",
        )
        after = self.registry.overview("project", self.study)
        self.assertFalse(after["holdout_registry_unopened"])
        self.assertEqual(after["holdout_access_attempts"], 5)
        self.assertTrue(verify_study_export(document)["execution_replayed"])

    def test_holdout_metadata_does_not_disclose_result_numbers(self):
        good = self.register()
        self.execute(good)
        self.select(good)
        trial = self.register(holdout(self.inputs), "holdout", "holdout")
        self.execute(trial)
        overview = self.registry.overview("project", self.study)
        self.assertTrue(
            all(
                "result" not in row and "summary" not in row
                for row in overview["trials"]
            )
        )
        self.assertEqual(overview["holdout_access_attempts"], 1)

