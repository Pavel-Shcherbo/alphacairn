"""Independent storage, transaction, disclosure and actual HTTP workbench controls."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
import hashlib
import http.client
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from alphacairn.research_desk import ResearchDesk, examples
from alphacairn.study_evidence import verify_study_export


class ResearchDeskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = examples()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "research.sqlite"
        self.desk = ResearchDesk(self.path)
        self.counter = 0
        self.study = self.op("create", definition=self.example["definition"])["id"]

    def op(self, action, request_key=None, **values):
        self.counter += 1
        params = {
            "action": action,
            "project": "review",
            "request_key": request_key or "request-" + str(self.counter),
            **values,
        }
        if action in ("run", "inspect", "export", "recover", "select", "compare"):
            params.update(actor="reviewer", reason="Independent synthetic control")
        if action in ("run", "inspect", "export", "recover", "select"):
            params.setdefault("study", self.study)
        return self.desk.dispatch(params)

    def register(self, control="baseline", partition="development", **kwargs):
        return self.op(
            "register",
            study=self.study,
            inputs=self.example["controls"][control],
            partition=partition,
            label=control,
            **kwargs,
        )["id"]

    def view(self, **values):
        return self.desk.dispatch(
            {"action": "view", "project": "review", "study": self.study, **values}
        )

    def holdout(self):
        trial = self.register()
        self.op("run", trial=trial)
        self.op("select", trial=trial)
        return self.register("holdout", "holdout")

    def test_complete_comparison_retains_success_incomplete_and_failed(self):
        trials = [
            self.register(control) for control in ("baseline", "incomplete", "invalid")
        ]
        self.op("run", trial=trials[0])
        with self.assertRaisesRegex(ValueError, "resolve every"):
            self.op("select", trial=trials[0])
        for trial in trials[1:]:
            self.op("run", trial=trial)
        value = self.view()
        self.assertEqual(
            [row["record"]["status"] for row in value["comparison"]["comparisons"]],
            ["succeeded", "incomplete", "failed"],
        )
        self.assertEqual(value["context"]["failed_trial_count"], 2)
        self.assertTrue(value["audit"]["passed"])
        self.op("select", trial=trials[0])
        with self.assertRaisesRegex(ValueError, "closed"):
            self.register()

    def test_independent_exact_equity_and_stress_reconciliation(self):
        trial = self.register()
        result = self.op("run", trial=trial)["result"]
        self.assertEqual(
            sum(Decimal(row["base_value"]) for row in result["exposures"]),
            Decimal("10948.90"),
        )
        for stress in result["stresses"]:
            self.assertEqual(
                sum(Decimal(row["pnl"]) for row in stress["components"]),
                Decimal(stress["pnl"]),
            )
            self.assertEqual(
                Decimal(stress["equity"]) - Decimal("10948.90"), Decimal(stress["pnl"])
            )
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(
                db.execute(
                    "SELECT status,generation FROM trials WHERE id=?", (trial,)
                ).fetchone(),
                ("succeeded", 3),
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM study_events WHERE kind='trial_finished'"
                ).fetchone()[0],
                1,
            )

    def test_default_view_withholds_holdout_and_never_logs_access(self):
        held = self.holdout()
        self.op("run", trial=held, acknowledge_holdout=True)
        for _ in range(3):
            value = self.view()
            row = value["comparison"]["comparisons"][-1]
            self.assertTrue(row["withheld"])
            self.assertIsNone(row["summary"])
            self.assertIsNone(row["error"])
            self.assertEqual(value["context"]["holdout_access_attempts"], 1)
            held_events = [
                event
                for event in value["events"]
                if event["payload"].get("trial") == held
            ]
            self.assertTrue(held_events)
            self.assertTrue(all(event["payload_redacted"] for event in held_events))
            self.assertTrue(
                all(
                    "contract" not in event["payload"]
                    and "error" not in event["payload"]
                    for event in held_events
                )
            )

    def test_each_holdout_action_requires_boolean_acknowledgement(self):
        held = self.holdout()
        for action in ("run", "inspect", "export"):
            for value in (None, False, 1, "true"):
                with self.assertRaisesRegex(ValueError, "acknowledge"):
                    self.op(action, trial=held, acknowledge_holdout=value)
        for value in (None, False, 1):
            with self.assertRaisesRegex(ValueError, "acknowledge"):
                self.op(
                    "compare",
                    study=self.study,
                    include_holdout=True,
                    acknowledge_holdout=value,
                )
        self.assertEqual(self.view()["context"]["holdout_access_attempts"], 0)

    def test_run_retry_and_receipt_recovery_after_restart_do_not_duplicate_access(self):
        held = self.holdout()
        first = self.op(
            "run", trial=held, request_key="holdout-run", acknowledge_holdout=True
        )
        self.desk = ResearchDesk(self.path)
        repeated = self.op(
            "run", trial=held, request_key="holdout-run", acknowledge_holdout=True
        )
        recovered = self.desk.dispatch(
            {"action": "receipt", "project": "review", "request_key": "holdout-run"}
        )
        self.assertEqual(first, repeated)
        self.assertEqual(first, recovered)
        self.assertEqual(self.view()["context"]["holdout_access_attempts"], 1)
        with self.assertRaisesRegex(ValueError, "another research operation"):
            self.op(
                "inspect",
                trial=held,
                request_key="holdout-run",
                acknowledge_holdout=True,
            )

    def test_select_and_export_receipts_recover_lost_responses(self):
        trial = self.register()
        self.op("run", trial=trial)
        selected = self.op("select", trial=trial, request_key="select")
        self.assertEqual(selected, self.op("select", trial=trial, request_key="select"))
        held = self.register("holdout", "holdout")
        self.op("run", trial=held, acknowledge_holdout=True)
        exported = self.op(
            "export", trial=held, request_key="export", acknowledge_holdout=True
        )
        self.assertEqual(
            exported,
            self.op(
                "export", trial=held, request_key="export", acknowledge_holdout=True
            ),
        )
        self.assertEqual(self.view()["context"]["holdout_access_attempts"], 2)
        self.assertTrue(verify_study_export(exported)["passed"])
        self.path.unlink()
        self.assertTrue(verify_study_export(exported)["execution_replayed"])

    def test_concurrent_identical_runs_commit_one_execution_and_receipt(self):
        trial = self.register()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: self.op("run", trial=trial, request_key="same-run"),
                    range(4),
                )
            )
        self.assertTrue(all(value == results[0] for value in results))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM study_events WHERE kind='trial_started'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM desk_receipts WHERE request_key='same-run'"
                ).fetchone()[0],
                1,
            )

    def test_failure_after_computation_rolls_back_result_events_and_response(self):
        trial = self.register()
        original = self.desk.operate

        def fail(*args):
            original(*args)
            raise RuntimeError("failure before response persistence")

        with patch.object(self.desk, "operate", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.op("run", trial=trial, request_key="atomic-run")
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(
                db.execute(
                    "SELECT status,result FROM trials WHERE id=?", (trial,)
                ).fetchone(),
                ("registered", None),
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM study_events WHERE kind='trial_started'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM desk_receipts WHERE request_key='atomic-run'"
                ).fetchone()[0],
                0,
            )
        self.assertEqual(
            self.op("run", trial=trial, request_key="atomic-run")["record"]["status"],
            "succeeded",
        )

    def test_oversized_response_rolls_back_selection(self):
        trial = self.register()
        self.op("run", trial=trial)
        with patch("alphacairn.research_desk.MAX_RESPONSE", 1):
            with self.assertRaisesRegex(ValueError, "response exceeds"):
                self.op("select", trial=trial)
        self.assertIsNone(self.view()["context"]["selection"])

    def test_read_views_and_cached_responses_obey_the_response_budget(self):
        trial = self.register()
        self.op("run", trial=trial, request_key="saved-large")
        with patch("alphacairn.research_desk.MAX_RESPONSE", 1):
            for params in (
                {"action": "view", "project": "review", "study": self.study},
                {"action": "list", "project": "review"},
                {
                    "action": "receipt",
                    "project": "review",
                    "request_key": "saved-large",
                },
            ):
                with self.assertRaisesRegex(ValueError, "response exceeds"):
                    self.desk.dispatch(params)
        self.assertEqual(self.view()["context"]["trials"][0]["status"], "succeeded")

    def test_project_and_selected_study_fences(self):
        trial = self.register()
        second = copy.deepcopy(self.example["definition"])
        second["name"] = "other-study"
        other = self.op("create", definition=second)["id"]
        with self.assertRaisesRegex(ValueError, "selected study"):
            self.op("run", study=other, trial=trial)
        with self.assertRaises(ValueError):
            self.desk.dispatch(
                {"action": "view", "project": "other-project", "study": self.study}
            )
        with self.assertRaises(ValueError):
            self.desk.dispatch(
                {
                    "action": "receipt",
                    "project": "other-project",
                    "request_key": "request-1",
                }
            )
        self.assertEqual(
            self.desk.dispatch({"action": "list", "project": "other-project"})[
                "studies"
            ],
            [],
        )

