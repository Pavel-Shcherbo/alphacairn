"""Scoped local research operations with atomic responses and coherent saved views."""

from contextlib import contextmanager
import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile

from .ledger import Ledger
from .instruments import timestamp, timestamp_text
from .market_model import canonical, digest
from .resources import examples_directory
from .risk_inputs import capture_risk_inputs
from .study_evidence import audit_study, compare_trials, export_trial
from .study_model import identity, key, prose
from .study_runner import run_trial, summary
from .study_store import StudyRegistry, decode

MAX_REQUEST = 8 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024


class BoundRegistry(StudyRegistry):
    """Keep existing registry operations in the caller's one request transaction."""

    def __init__(self, registry, db):
        self.path, self.clock, self.db = registry.path, registry.clock, db

    @contextmanager
    def transaction(self, write=True):
        yield self.db


def fields(value, required, optional=()):
    if (
        not isinstance(value, dict)
        or not set(required) <= set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise ValueError("research request has missing or unsupported fields")


def examples():
    directory = examples_directory()

    def read(name):
        return json.loads((directory / name).read_bytes())

    with tempfile.TemporaryDirectory(prefix="alphacairn-risk-example-") as temporary:
        ledger = Ledger(
            Path(temporary) / "example.sqlite", read("portfolio-account.json")
        )
        ledger.apply_batch(read("portfolio-events.json"))
        inputs = capture_risk_inputs(
            ledger.path,
            read("risk-control.json"),
            read("risk-history.json"),
            read("risk-quotes.json"),
        )
    incomplete = copy.deepcopy(inputs)
    incomplete["history"]["observations"] = incomplete["history"]["observations"][:2]
    invalid = copy.deepcopy(inputs)
    invalid["quotes"]["marks"]["crypto:demo"]["timestamp"] = "2026-01-03T00:00:00Z"
    later = copy.deepcopy(inputs)
    shift = lambda value: timestamp_text(timestamp(value) + timedelta(days=31))
    for field in ("as_of", "history_start", "history_end"):
        later["configuration"][field] = shift(later["configuration"][field])
    later["quotes"]["as_of"] = shift(later["quotes"]["as_of"])
    for quote in list(later["quotes"]["marks"].values()) + list(
        later["quotes"]["fx"].values()
    ):
        quote["timestamp"] = shift(quote["timestamp"])
    for point in later["history"]["observations"]:
        point["at"] = shift(point["at"])
        point["available_at"] = shift(point["available_at"])
    for value in (incomplete, invalid, later):
        value["sha256"] = digest({k: v for k, v in value.items() if k != "sha256"})
    return {
        "definition": read("study-risk-plan.json"),
        "inputs": inputs,
        "controls": {
            "baseline": inputs,
            "incomplete": incomplete,
            "invalid": invalid,
            "holdout": later,
        },
        "source": "Synthetic portfolio and declared price/FX shocks; not a market feed",
    }


class ResearchDesk:
    def __init__(self, path):
        self.registry = StudyRegistry(path)
        with self.registry.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS desk_receipts(project TEXT NOT NULL,request_key TEXT NOT NULL,request_sha256 TEXT NOT NULL,result BLOB NOT NULL,result_sha256 TEXT NOT NULL,PRIMARY KEY(project,request_key))"
            )

    def dispatch(self, params):
        fields(
            params,
            ("action",),
            (
                "project",
                "study",
                "trial",
                "definition",
                "inputs",
                "partition",
                "label",
                "request_key",
                "actor",
                "reason",
                "include_holdout",
                "acknowledge_holdout",
                "generation",
                "after",
                "limit",
            ),
        )
        if len(canonical(params)) > MAX_REQUEST:
            raise ValueError("research request exceeds 8 MiB")
        action = params["action"]
        if action == "examples":
            fields(params, ("action",))
            return examples()
        project = identity(params.get("project"), "project")
        if action in ("list", "view", "receipt"):
            with self.registry.transaction(False) as db:
                registry = BoundRegistry(self.registry, db)
                if action == "list":
                    fields(params, ("action", "project"))
                    return self.bounded_response(self.list_in_view(registry, project))
                if action == "receipt":
                    fields(params, ("action", "project", "request_key"))
                    row = db.execute(
                        "SELECT result,result_sha256 FROM desk_receipts WHERE project=? AND request_key=?",
                        (project, key(params["request_key"])),
                    ).fetchone()
                    if row is None:
                        raise ValueError("request receipt not found in this project")
                    return self.receipt(row)
                fields(params, ("action", "project", "study"), ("after", "limit"))
                return self.bounded_response(
                    self.view(
                        registry,
                        project,
                        params["study"],
                        params.get("after", 0),
                        params.get("limit", 50),
                    )
                )
        request_key = key(params.get("request_key"))
        request_sha = digest(params)
        # Foreground local requests are one transaction, including computation and
        # response recording. A process failure leaves the registered trial ready.
        with self.registry.transaction() as db:
            prior = db.execute(
                "SELECT * FROM desk_receipts WHERE project=? AND request_key=?",
                (project, request_key),
            ).fetchone()
            if prior is not None:
                if prior["request_sha256"] != request_sha:
                    raise ValueError(
                        "request key identifies another research operation"
                    )
                return self.receipt(prior)
            if db.execute("SELECT count(*) FROM desk_receipts").fetchone()[0] >= 10000:
                raise ValueError(
                    "research desk reached 10,000 retained request receipts"
                )
            registry = BoundRegistry(self.registry, db)
            result = self.operate(registry, project, action, params)
            encoded = canonical(result)
            if len(encoded) > MAX_RESPONSE:
                raise ValueError(
                    "research response exceeds 16 MiB; use the CLI for larger evidence"
                )
            db.execute(
                "INSERT INTO desk_receipts VALUES(?,?,?,?,?)",
                (project, request_key, request_sha, encoded, digest(result)),
            )
            return result

