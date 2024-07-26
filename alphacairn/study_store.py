"""Immutable trial inputs, complete attempt history and explicit holdout access."""

from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid

from .market_model import canonical, digest
from .study_model import (
    declaration,
    identity,
    key,
    prose,
    trial_contract,
    require_window,
)

TERMINAL = {"succeeded", "incomplete", "failed", "interrupted"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS studies(
 id TEXT PRIMARY KEY,project TEXT NOT NULL,name TEXT NOT NULL,
 definition BLOB NOT NULL,definition_sha256 TEXT NOT NULL,created REAL NOT NULL,
 selection TEXT,UNIQUE(project,name)
);
CREATE TABLE IF NOT EXISTS trials(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,
 study_id TEXT NOT NULL REFERENCES studies(id),request_key TEXT NOT NULL,
 input_sha256 TEXT NOT NULL,inputs BLOB NOT NULL,contract BLOB NOT NULL,
 partition TEXT NOT NULL,label TEXT NOT NULL,status TEXT NOT NULL,
 generation INTEGER NOT NULL,token TEXT,lease_until REAL,result BLOB,error BLOB,
 created REAL NOT NULL,finished REAL,UNIQUE(study_id,request_key)
);
CREATE INDEX IF NOT EXISTS trials_study ON trials(study_id,sequence);
CREATE TABLE IF NOT EXISTS study_events(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,study_id TEXT NOT NULL REFERENCES studies(id),
 kind TEXT NOT NULL,payload BLOB NOT NULL,previous_sha256 TEXT NOT NULL,
 sha256 TEXT NOT NULL,created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS study_event_order ON study_events(study_id,sequence);
"""


def decode(raw):
    return json.loads(raw)


def trial_meta(row):
    return {
        field: row[field]
        for field in (
            "id",
            "sequence",
            "study_id",
            "partition",
            "label",
            "input_sha256",
            "status",
            "generation",
            "created",
            "finished",
            "lease_until",
        )
    }


class StudyRegistry:
    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or time.time
        if self.path.is_symlink():
            raise ValueError("study database cannot be a symlink")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.transaction() as db:
            for sql in SCHEMA.split(";"):
                if sql.strip():
                    db.execute(sql)
        self.path.chmod(0o600)

    def now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid registry clock")
        return value

    @contextmanager
    def transaction(self, write=True):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        db.execute("PRAGMA max_page_count=" + str(256 * 1024 * 1024 // page_size))
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def study(self, db, project, study):
        identity(project, "project")
        identity(study, "study ID")
        row = db.execute(
            "SELECT * FROM studies WHERE project=? AND id=?", (project, study)
        ).fetchone()
        if row is None:
            raise ValueError("study not found in this project")
        if digest(decode(row["definition"])) != row["definition_sha256"]:
            raise ValueError("study declaration identity changed")
        return row

    def trial(self, db, project, trial):
        identity(trial, "trial ID")
        row = db.execute(
            "SELECT t.* FROM trials t JOIN studies s ON s.id=t.study_id WHERE s.project=? AND t.id=?",
            (project, trial),
        ).fetchone()
        if row is None:
            raise ValueError("trial not found in this project")
        return row

    def event(self, db, study, kind, payload):
        prior = db.execute(
            "SELECT sha256 FROM study_events WHERE study_id=? ORDER BY sequence DESC LIMIT 1",
            (study,),
        ).fetchone()
        parent = prior[0] if prior else digest([])
        now = self.now()
        content = {
            "study": study,
            "kind": kind,
            "payload": payload,
            "previous_sha256": parent,
            "created": now,
        }
        sha = digest(content)
        db.execute(
            "INSERT INTO study_events(study_id,kind,payload,previous_sha256,sha256,created) VALUES(?,?,?,?,?,?)",
            (study, kind, canonical(payload), parent, sha, now),
        )

    def create(self, project, definition):
        identity(project, "project")
        plan = declaration(definition)
        with self.transaction() as db:
            prior = db.execute(
                "SELECT * FROM studies WHERE project=? AND name=?",
                (project, plan["name"]),
            ).fetchone()
            if prior is not None:
                if prior["definition_sha256"] != digest(plan):
                    raise ValueError(
                        "study name already identifies another immutable declaration"
                    )
                return {
                    "id": prior["id"],
                    "definition": plan,
                    "created": prior["created"],
                }
            if db.execute("SELECT count(*) FROM studies").fetchone()[0] >= 200:
                raise ValueError("local registry reached 200 studies")
            study = uuid.uuid4().hex
            now = self.now()
            db.execute(
                "INSERT INTO studies VALUES(?,?,?,?,?,?,NULL)",
                (study, project, plan["name"], canonical(plan), digest(plan), now),
            )
            self.event(db, study, "study_created", {"definition_sha256": digest(plan)})
            return {"id": study, "definition": plan, "created": now}

    def register(self, project, study, inputs, partition, request_key, label):
        key(request_key)
        prose(label, "trial label", 200)
        with self.transaction(False) as db:
            plan = decode(self.study(db, project, study)["definition"])
        contract = trial_contract(plan["family"], inputs)
        require_window(plan, partition, contract)
        fingerprint = digest(
            {"inputs": inputs["sha256"], "partition": partition, "label": label}
        )
        with self.transaction() as db:
            row = self.study(db, project, study)
            prior = db.execute(
                "SELECT * FROM trials WHERE study_id=? AND request_key=?",
                (study, request_key),
            ).fetchone()
            if prior is not None:
                if (
                    digest(
                        {
                            "inputs": prior["input_sha256"],
                            "partition": prior["partition"],
                            "label": prior["label"],
                        }
                    )
                    != fingerprint
                ):
                    raise ValueError("trial request key identifies different inputs")
                return trial_meta(prior)
            if (
                db.execute(
                    "SELECT count(*) FROM trials WHERE study_id=?", (study,)
                ).fetchone()[0]
                >= 100
            ):
                raise ValueError("study reached 100 registered trials")
            selection = decode(row["selection"]) if row["selection"] else None
            if partition == "development" and selection is not None:
                raise ValueError("development registration is closed after selection")
            if partition == "holdout":
                if selection is None:
                    raise ValueError(
                        "lock a completed development selection before registering holdout inputs"
                    )
                if contract["recipe_sha256"] != selection["recipe_sha256"]:
                    raise ValueError(
                        "holdout recipe differs from the locked development selection"
                    )
            trial = uuid.uuid4().hex
            now = self.now()
            db.execute(
                "INSERT INTO trials(id,study_id,request_key,input_sha256,inputs,contract,partition,label,status,generation,created) VALUES(?,?,?,?,?,?,?,?,'registered',1,?)",
                (
                    trial,
                    study,
                    request_key,
                    inputs["sha256"],
                    canonical(inputs),
                    canonical(contract),
                    partition,
                    label,
                    now,
                ),
            )
            self.event(
                db,
                study,
                "trial_registered",
                {
                    "trial": trial,
                    "input_sha256": inputs["sha256"],
                    "request_sha256": fingerprint,
                    "partition": partition,
                    "contract": contract,
                },
            )
            return trial_meta(self.trial(db, project, trial))

    def access(self, db, row, purpose, actor, reason):
        prose(actor, "actor", 100)
        prose(reason, "access reason")
        if row["partition"] == "holdout":
            self.event(
                db,
                row["study_id"],
                "holdout_access",
                {
                    "trial": row["id"],
                    "purpose": purpose,
                    "actor": actor,
                    "reason": reason,
                },
            )

    def verify_trial(self, db, row):
        inputs = decode(row["inputs"])
        if (
            inputs.get("sha256") != row["input_sha256"]
            or digest({k: v for k, v in inputs.items() if k != "sha256"})
            != row["input_sha256"]
        ):
            raise ValueError("retained trial input identity changed")
        history = db.execute(
            "SELECT * FROM study_events WHERE study_id=? ORDER BY sequence LIMIT 20001",
            (row["study_id"],),
        ).fetchall()
        if len(history) > 20000:
            raise ValueError("complete trial audit exceeds 20,000 study events")
        items = [{**dict(item), "payload": decode(item["payload"])} for item in history]
        from .study_evidence import check_chain

        check_chain(row["study_id"], items)
        state = None
        finish = None
        for item in items:
            value = item["payload"]
            if value.get("trial") != row["id"]:
                continue
            if item["kind"] == "trial_registered":
                if value["input_sha256"] != row["input_sha256"] or value[
                    "contract"
                ] != decode(row["contract"]):
                    raise ValueError("trial data differs from registration history")
                state = "registered"
            elif item["kind"] == "trial_started":
                state = "running"
            elif item["kind"] == "trial_finished":
                state = value["status"]
                finish = value
            elif item["kind"] == "trial_interrupted":
                state = "interrupted"
        if state != row["status"]:
            raise ValueError("trial state differs from its history")
        report = decode(row["result"]) if row["result"] else None
        error = decode(row["error"]) if row["error"] else None
        if state in ("registered", "running", "interrupted") and (
            report is not None or error is not None
        ):
            raise ValueError("unfinished trial contains an uncommitted result")
        if finish is not None and (
            finish["result_sha256"] != (digest(report) if report else None)
            or finish["error"] != error
        ):
            raise ValueError("trial result differs from completion history")

    def read(self, project, trial, *, actor, reason, purpose="inspect"):
        if purpose not in ("inspect", "export"):
            raise ValueError("unknown trial read purpose")
        with self.transaction() as db:
            row = self.trial(db, project, trial)
            self.verify_trial(db, row)
            self.access(db, row, purpose, actor, reason)
            return {
                "record": trial_meta(row),
                "inputs": decode(row["inputs"]),
                "contract": decode(row["contract"]),
                "result": decode(row["result"]) if row["result"] else None,
                "error": decode(row["error"]) if row["error"] else None,
            }

    def overview(self, project, study):
        with self.transaction(False) as db:
            row = self.study(db, project, study)
            trials = [
                trial_meta(t)
                for t in db.execute(
                    "SELECT * FROM trials WHERE study_id=? ORDER BY sequence", (study,)
                )
            ]
            accesses = db.execute(
                "SELECT count(*) FROM study_events WHERE study_id=? AND kind='holdout_access'",
                (study,),
            ).fetchone()[0]
            return {
                "id": study,
                "definition": decode(row["definition"]),
                "selection": decode(row["selection"]) if row["selection"] else None,
                "trials": trials,
                "registered_trial_count": len(trials),
                "failed_trial_count": sum(
                    t["status"] in ("failed", "incomplete", "interrupted")
                    for t in trials
                ),
                "holdout_access_attempts": accesses,
                "holdout_registry_unopened": accesses == 0,
                "scope": "Registry-local access accounting; original data may have been accessed elsewhere",
            }

    def select(self, project, study, trial, *, actor, reason):
        prose(actor, "selection actor", 100)
        prose(reason, "selection reason")
        with self.transaction() as db:
            row = self.study(db, project, study)
            if row["selection"] is not None:
                raise ValueError("study selection is already locked")
            chosen = self.trial(db, project, trial)
            self.verify_trial(db, chosen)
            if (
                chosen["study_id"] != study
                or chosen["partition"] != "development"
                or chosen["status"] != "succeeded"
            ):
                raise ValueError(
                    "selection requires a successful development trial in this study"
                )
            pending = db.execute(
                "SELECT 1 FROM trials WHERE study_id=? AND partition='development' AND status IN ('registered','running') LIMIT 1",
                (study,),
            ).fetchone()
            if pending:
                raise ValueError(
                    "resolve every registered development trial before selection"
                )
            selection = {
                "trial": trial,
                "recipe_sha256": decode(chosen["contract"])["recipe_sha256"],
                "actor": actor,
                "reason": reason,
                "created": self.now(),
            }
            db.execute(
                "UPDATE studies SET selection=? WHERE id=?",
                (canonical(selection), study),
            )
            self.event(db, study, "selection_locked", selection)
            return selection

