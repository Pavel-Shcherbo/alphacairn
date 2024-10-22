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

    def test_window_boundaries_reject_cross_partition_trials(self):
        with self.assertRaises(ValueError):
            self.register(self.inputs, "wrong-window", "holdout")
        bad = copy.deepcopy(self.plan)
        bad["holdout"]["start"] = bad["development"]["end"]
        with self.assertRaises(ValueError):
            declaration(bad)

    def test_cached_result_retry_does_not_execute_twice(self):
        trial = self.register()
        first = self.execute(trial)
        with patch(
            "alphacairn.study_runner.compute",
            side_effect=AssertionError("repeated execution"),
        ):
            again = self.execute(trial)
        self.assertEqual(first, again)
        self.assertEqual(len(audit_study(self.registry, "project", self.study)[1]), 4)

    def test_rehashed_wrong_result_cannot_be_read_from_cache(self):
        trial = self.register()
        self.execute(trial)
        with self.registry.transaction() as db:
            row = self.registry.trial(db, "project", trial["id"])
            report = json.loads(row["result"])
            report["valuation"]["equity"] = "999999"
            resign(report)
            db.execute(
                "UPDATE trials SET result=? WHERE id=?",
                (canonical(report), trial["id"]),
            )
        with self.assertRaisesRegex(ValueError, "completion history"):
            self.execute(trial)
        with self.assertRaises(ValueError):
            audit_study(self.registry, "project", self.study)
        with self.assertRaises(ValueError):
            self.registry.read("project", trial["id"], actor="a", reason="b")

    def test_exports_remain_verifiable_without_database(self):
        trial = self.register()
        self.execute(trial)
        document = export_trial(
            self.registry,
            "project",
            trial["id"],
            actor="reviewer",
            reason="Portable control",
        )
        self.registry.path.unlink()
        proof = verify_study_export(document)
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["summary"]["equity"], "10948.90")

    def test_omitting_failed_attempt_from_export_breaks_complete_context(self):
        good = self.register()
        self.execute(good)
        other = self.register(key="other")
        self.execute(other)
        document = export_trial(
            self.registry, "project", good["id"], actor="a", reason="b"
        )
        document["context"]["trials"].pop()
        document["context"]["registered_trial_count"] -= 1
        resign(document)
        with self.assertRaisesRegex(ValueError, "omitted"):
            verify_study_export(document)

    def test_removing_holdout_access_count_or_chain_event_is_detected(self):
        good = self.register()
        self.execute(good)
        self.select(good)
        trial = self.register(holdout(self.inputs), "holdout", "holdout")
        self.execute(trial)
        document = export_trial(
            self.registry, "project", trial["id"], actor="a", reason="b"
        )
        document["context"]["holdout_access_attempts"] = 0
        document["context"]["holdout_registry_unopened"] = True
        resign(document)
        with self.assertRaisesRegex(ValueError, "access"):
            verify_study_export(document)

    def test_interrupted_trial_is_retained_without_false_replay_claim(self):
        now = [100.0]
        registry = StudyRegistry(self.root / "recovery.sqlite", clock=lambda: now[0])
        study = registry.create("project", self.plan)["id"]
        trial = registry.register(
            "project", study, self.inputs, "development", "one", "Interrupted control"
        )

        def crash(*_):
            raise KeyboardInterrupt()

        with (
            patch("alphacairn.study_runner.compute", crash),
            self.assertRaises(KeyboardInterrupt),
        ):
            run_trial(registry, "project", trial["id"], actor="a", reason="b")
        with self.assertRaises(ValueError):
            registry.recover("project", trial["id"], 2, actor="a", reason="b")
        now[0] = 701.0
        registry.recover("project", trial["id"], 2, actor="a", reason="b")
        proof = verify_study_export(
            export_trial(registry, "project", trial["id"], actor="a", reason="b")
        )
        self.assertFalse(proof["execution_replayed"])
        self.assertFalse(proof["complete"])
        with self.assertRaises(ValueError):
            registry.recover("project", trial["id"], 2, actor="a", reason="b")

    def test_commit_time_lease_expiry_rolls_back_result_and_event(self):
        now = [100.0]
        self.registry.clock = lambda: now[0]
        trial = self.register()
        from alphacairn.study_runner import compute

        def delayed(*args):
            result = compute(*args)
            now[0] = 701.0
            return result

        with (
            patch("alphacairn.study_runner.compute", delayed),
            self.assertRaisesRegex(ValueError, "lease"),
        ):
            self.execute(trial)
        overview = self.registry.overview("project", self.study)
        self.assertEqual(overview["trials"][0]["status"], "running")
        self.assertEqual(len(audit_study(self.registry, "project", self.study)[1]), 3)

    def test_concurrent_registration_and_selection_are_serialized(self):
        def register(_):
            return StudyRegistry(self.registry.path).register(
                "project",
                self.study,
                self.inputs,
                "development",
                "same",
                "Same control",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(register, range(4)))
        self.assertEqual(len({v["id"] for v in values}), 1)
        self.execute(values[0])

        def select(_):
            try:
                self.select(values[0])
                return True
            except ValueError:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(select, range(4))), 1)

    def test_strategy_family_runs_real_captured_execution(self):
        catalog = MarketCatalog(self.root / "market.sqlite", create=True)
        config = load("strategy-control.json")
        for kind, file in [
            ("bar", "strategy-bars.json"),
            ("membership", "strategy-universe.json"),
        ]:
            catalog.ingest(
                config["source"], kind, canonical(load(file)), request_key=kind
            )
        inputs = capture_strategy(catalog, config)
        plan = copy.deepcopy(self.plan)
        plan.update(
            name="synthetic-strategy-registry",
            family="strategy",
            development={
                "start": "2020-01-01T00:00:00Z",
                "end": "2020-01-10T00:00:00Z",
            },
            holdout={"start": "2020-02-01T00:00:00Z", "end": "2020-02-10T00:00:00Z"},
        )
        study = self.registry.create("project", plan)["id"]
        trial = self.registry.register(
            "project",
            study,
            inputs,
            "development",
            "strategy",
            "Real captured strategy",
        )
        result = self.execute(trial)
        self.assertEqual(result["summary"]["equity"], "86.50")
        self.assertEqual(result["summary"]["fills"], 6)
        self.assertTrue(
            verify_study_export(
                export_trial(
                    self.registry, "project", trial["id"], actor="a", reason="b"
                )
            )["passed"]
        )

    def test_comparison_defaults_withhold_holdout_and_opening_is_logged(self):
        good = self.register()
        self.execute(good)
        self.select(good)
        trial = self.register(holdout(self.inputs), "holdout", "holdout")
        self.execute(trial)
        before = self.registry.overview("project", self.study)[
            "holdout_access_attempts"
        ]
        comparison = compare_trials(
            self.registry,
            "project",
            self.study,
            actor="reviewer",
            reason="Compare development",
        )
        self.assertEqual(len(comparison["comparisons"]), 2)
        self.assertIsNone(comparison["comparisons"][1]["summary"])
        self.assertTrue(comparison["comparisons"][1]["withheld"])
        self.assertEqual(
            self.registry.overview("project", self.study)["holdout_access_attempts"],
            before,
        )
        opened = compare_trials(
            self.registry,
            "project",
            self.study,
            actor="reviewer",
            reason="Review holdout explicitly",
            include_holdout=True,
        )
        self.assertEqual(opened["comparisons"][1]["summary"]["equity"], "10948.90")
        self.assertEqual(
            self.registry.overview("project", self.study)["holdout_access_attempts"],
            before + 1,
        )
        self.assertTrue(audit_study(self.registry, "project", self.study)[2]["passed"])

    def test_interrupted_trial_cannot_carry_a_fabricated_result(self):
        self.registry.clock = lambda: 100.0
        trial = self.register()
        with (
            patch("alphacairn.study_runner.compute", side_effect=KeyboardInterrupt()),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.execute(trial)
        self.registry.clock = lambda: 701.0
        self.registry.recover(
            "project", trial["id"], 2, actor="reviewer", reason="Interrupted worker"
        )
        document = export_trial(
            self.registry,
            "project",
            trial["id"],
            actor="reviewer",
            reason="Retain interrupted proof",
        )
        document["trial"]["result"] = {"invented": "success"}
        resign(document)
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            verify_study_export(document)
        with self.registry.transaction() as db:
            db.execute(
                "UPDATE trials SET result=? WHERE id=?",
                (canonical({"invented": "success"}), trial["id"]),
            )
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            self.registry.read(
                "project", trial["id"], actor="reviewer", reason="Inspect"
            )

    def test_cli_complete_flow_and_create_only_export(self):
        definition = self.root / "study.json"
        definition.write_text(json.dumps(self.plan))
        inputs = self.root / "inputs.json"
        inputs.write_bytes(canonical(self.inputs))
        args = [
            sys.executable,
            "-m",
            "alphacairn.studies",
            "--database",
            str(self.root / "cli.sqlite"),
            "--project",
            "project",
        ]

        def cli(*tail, expected=0):
            result = subprocess.run(
                args + list(map(str, tail)), capture_output=True, text=True
            )
            self.assertEqual(result.returncode, expected, result.stderr)
            return json.loads(result.stdout) if result.stdout else None

        study = cli("create", definition)["id"]
        trial = cli(
            "register",
            study,
            inputs,
            "--partition",
            "development",
            "--request-key",
            "one",
            "--label",
            "CLI control",
        )["id"]
        cli("run", trial, "--actor", "reviewer", "--reason", "Control")
        cli(
            "select",
            trial,
            "--study",
            study,
            "--actor",
            "reviewer",
            "--reason",
            "Freeze choice",
        )
        output = self.root / "export.json"
        cli(
            "export",
            trial,
            "--output",
            output,
            "--actor",
            "reviewer",
            "--reason",
            "Review",
        )
        self.assertTrue(cli("verify", output)["passed"])
        recovery = StudyRegistry(self.root / "cli.sqlite", clock=lambda: 100.0)
        plan = copy.deepcopy(self.plan)
        plan["name"] = "cli-recovery"
        later_study = recovery.create("project", plan)["id"]
        pending = recovery.register(
            "project",
            later_study,
            self.inputs,
            "development",
            "pending",
            "Recovery control",
        )
        with (
            patch("alphacairn.study_runner.compute", side_effect=KeyboardInterrupt()),
            self.assertRaises(KeyboardInterrupt),
        ):
            run_trial(
                recovery,
                "project",
                pending["id"],
                actor="reviewer",
                reason="Interrupted local run",
            )
        recovered = cli(
            "recover",
            pending["id"],
            "--generation",
            2,
            "--actor",
            "reviewer",
            "--reason",
            "Reconcile expired run",
            expected=1,
        )
        self.assertEqual(recovered["status"], "interrupted")

        cli(
            "export",
            trial,
            "--output",
            output,
            "--actor",
            "reviewer",
            "--reason",
            "Review",
            expected=2,
        )


if __name__ == "__main__":
    unittest.main()
