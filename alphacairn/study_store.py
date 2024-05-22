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


