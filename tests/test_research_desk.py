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

    def test_request_identity_conflict_does_not_register_another_trial(self):
        self.register(request_key="one-input")
        with self.assertRaisesRegex(ValueError, "another research operation"):
            self.register("incomplete", request_key="one-input")
        self.assertEqual(self.view()["context"]["registered_trial_count"], 1)

    def test_corrupt_receipt_or_trial_result_is_not_reported_as_valid(self):
        trial = self.register()
        self.op("run", trial=trial, request_key="cached")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "UPDATE desk_receipts SET result=? WHERE request_key='cached'", (b"{}",)
            )
        with self.assertRaisesRegex(ValueError, "response identity"):
            self.op("run", trial=trial, request_key="cached")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE trials SET result=? WHERE id=?", (b"{}", trial))
        with self.assertRaisesRegex(ValueError, "completion history"):
            self.view()

    def test_paged_history_is_coherent_and_duplicate_free(self):
        trial = self.register()
        self.op("run", trial=trial)
        first = self.view(limit=2)
        second = self.view(limit=2, after=first["next_after"])
        self.assertTrue(first["has_more"])
        ids = [event["sequence"] for event in first["events"] + second["events"]]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(first["audit"]["event_head"], second["audit"]["event_head"])
        self.assertEqual(first["context"], second["context"])
        for value in (-1, True):
            with self.assertRaises(ValueError):
                self.view(after=value)

    def test_expired_cli_run_can_be_recovered_with_a_generation_fence(self):
        trial = self.register()
        with self.desk.registry.transaction() as db:
            db.execute(
                "UPDATE trials SET status='running',generation=2,token='old',lease_until=1 WHERE id=?",
                (trial,),
            )
            self.desk.registry.event(
                db, self.study, "trial_started", {"trial": trial, "generation": 2}
            )
        with self.assertRaises(ValueError):
            self.op("recover", trial=trial, generation=1)
        recovered = self.op("recover", trial=trial, generation=2)
        self.assertEqual(recovered["status"], "interrupted")
        self.assertTrue(self.view()["audit"]["passed"])

    def test_strategy_inputs_run_through_the_same_browser_contract(self):
        from alphacairn.market_store import MarketCatalog
        from alphacairn.market_model import canonical
        from alphacairn.resources import examples_directory
        from alphacairn.strategy_inputs import capture_strategy

        read = lambda name: json.loads((examples_directory() / name).read_bytes())
        catalog = MarketCatalog(Path(self.temp.name) / "market.sqlite", create=True)
        config = read("strategy-control.json")
        for kind, file in [
            ("bar", "strategy-bars.json"),
            ("membership", "strategy-universe.json"),
        ]:
            catalog.ingest(
                config["source"], kind, canonical(read(file)), request_key=kind
            )
        inputs = capture_strategy(catalog, config)
        plan = copy.deepcopy(self.example["definition"])
        plan.update(
            name="strategy-browser",
            family="strategy",
            development={
                "start": "2020-01-01T00:00:00Z",
                "end": "2020-01-10T00:00:00Z",
            },
            holdout={"start": "2020-02-01T00:00:00Z", "end": "2020-02-10T00:00:00Z"},
        )
        study = self.op("create", definition=plan)["id"]
        trial = self.op(
            "register",
            study=study,
            inputs=inputs,
            partition="development",
            label="Captured strategy",
        )["id"]
        result = self.op("run", study=study, trial=trial)
        self.assertEqual(result["summary"]["equity"], "86.50")
        self.assertEqual(result["summary"]["fills"], 6)
        self.assertTrue(
            verify_study_export(self.op("export", study=study, trial=trial))["passed"]
        )

    def test_process_termination_during_foreground_run_preserves_registered_attempt(
        self,
    ):
        trial = self.register()
        script = """
import sys,time
from unittest.mock import patch
from alphacairn.research_desk import ResearchDesk
from alphacairn.study_runner import compute

def slow(*args):
    print('computing',flush=True)
    time.sleep(20)
    return compute(*args)
with patch('alphacairn.study_runner.compute',slow):
    ResearchDesk(sys.argv[1]).dispatch({'action':'run','project':'review','study':sys.argv[2],'trial':sys.argv[3],'request_key':'terminated-run','actor':'process-reviewer','reason':'Interruption control'})
"""
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(self.path), self.study, trial],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            ready, _, _ = select.select([child.stdout], [], [], 5)
            self.assertTrue(ready)
            self.assertEqual(child.stdout.readline().strip(), "computing")
            child.kill()
            child.communicate(timeout=5)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
        value = self.view()
        self.assertEqual(value["context"]["trials"][0]["status"], "registered")
        self.assertTrue(value["audit"]["passed"])
        result = self.op("run", trial=trial, request_key="terminated-run")
        self.assertEqual(result["record"]["status"], "succeeded")

    def test_invalid_payloads_and_input_hashes_have_no_effect(self):
        for value in (
            [],
            {"action": "list", "project": "review", "path": "/tmp/foreign"},
            {"action": "list"},
            {"action": "unsupported", "project": "review", "request_key": "x"},
        ):
            with self.assertRaises((ValueError, TypeError)):
                self.desk.dispatch(value)
        damaged = copy.deepcopy(self.example["inputs"])
        damaged["quotes"]["as_of"] = "2030-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            self.op(
                "register",
                study=self.study,
                inputs=damaged,
                partition="development",
                label="bad hash",
            )
        self.assertEqual(self.view()["context"]["registered_trial_count"], 0)


class ResearchHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        env = os.environ.copy()
        env["ALPHACAIRN_STATE_DIR"] = cls.temp.name
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "alphacairn.web", "--port", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        ready, _, _ = select.select([cls.process.stdout], [], [], 8)
        if not ready:
            cls.process.terminate()
            raise RuntimeError("workbench did not start")
        cls.port = int(cls.process.stdout.readline().strip().rsplit(":", 1)[1])

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.communicate(timeout=5)
        cls.temp.cleanup()

    def request(self, payload=None, path="/api/research", headers=None, method="POST"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(connection.close)
        head = {"Content-Type": "application/json", "X-Local-Request": "1"}
        if headers:
            head.update(headers)
        raw = json.dumps(payload) if isinstance(payload, dict) else payload
        connection.request(method, path, raw, head)
        response = connection.getresponse()
        body = response.read()
        return response.status, (
            json.loads(body)
            if response.getheader("Content-Type", "").startswith("application/json")
            else body
        )

    def test_actual_http_create_register_run_and_refresh(self):
        code, example = self.request({"action": "examples"})
        self.assertEqual(code, 200)
        project = "http-lifecycle"
        code, study = self.request(
            {
                "action": "create",
                "project": project,
                "request_key": "create",
                "definition": example["definition"],
            }
        )
        self.assertEqual(code, 200)
        code, trial = self.request(
            {
                "action": "register",
                "project": project,
                "study": study["id"],
                "request_key": "register",
                "inputs": example["inputs"],
                "partition": "development",
                "label": "HTTP baseline",
            }
        )
        self.assertEqual(code, 200)
        code, result = self.request(
            {
                "action": "run",
                "project": project,
                "study": study["id"],
                "trial": trial["id"],
                "request_key": "run",
                "actor": "http-reviewer",
                "reason": "Local HTTP control",
            }
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["summary"]["equity"], "10948.90")
        code, value = self.request(
            {"action": "view", "project": project, "study": study["id"]}
        )
        self.assertEqual(code, 200)
        self.assertTrue(value["audit"]["passed"])

    def test_foreign_host_origin_and_missing_local_header_rejected(self):
        for headers in (
            {"Host": "outside.example"},
            {"Origin": "https://outside.example"},
            {"X-Local-Request": "0"},
        ):
            self.assertEqual(
                self.request({"action": "list", "project": "local"}, headers=headers)[
                    0
                ],
                403,
            )

    def test_duplicate_keys_nonfinite_numbers_and_routes_rejected(self):
        for raw in (
            '{"action":"list","action":"examples"}',
            '{"action":"list","project":NaN}',
            "[]",
        ):
            self.assertEqual(self.request(raw)[0], 400)
        self.assertEqual(self.request({}, path="/api/research/unknown")[0], 404)
        self.assertEqual(self.request(method="GET")[0], 404)

    def test_request_byte_bounds_and_content_type_reject_before_work(self):
        self.assertEqual(
            self.request("{}", headers={"Content-Length": str(8 * 1024 * 1024 + 1)})[0],
            400,
        )
        self.assertEqual(
            self.request("{}", headers={"Content-Type": "text/plain"})[0], 400
        )

