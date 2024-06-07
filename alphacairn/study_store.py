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

