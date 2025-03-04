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

