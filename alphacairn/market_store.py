"""Append-only local market revisions and point-in-time snapshots."""

import hashlib
import sqlite3
import time
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

from .market_model import (
    MAX_BYTES,
    MAX_ROWS,
    canonical,
    decode,
    digest,
    identifier,
    instant,
    observation,
    record_key,
    snapshot_identity,
    validate_query,
    verify_snapshot,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches(
 id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL,
 recorded_at TEXT NOT NULL, raw_sha256 TEXT NOT NULL, raw BLOB NOT NULL,
 row_count INTEGER NOT NULL, normalized_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations(
 source TEXT NOT NULL, kind TEXT NOT NULL, identity TEXT NOT NULL,
 published_at TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(id),
 instrument TEXT NOT NULL, effective TEXT NOT NULL, payload TEXT NOT NULL,
 sha256 TEXT NOT NULL, PRIMARY KEY(source,kind,identity,published_at));
CREATE INDEX IF NOT EXISTS observation_lookup ON observations(source,kind,instrument,effective,published_at);
CREATE TABLE IF NOT EXISTS imports(
 source TEXT NOT NULL, request_key TEXT NOT NULL, batch_id TEXT NOT NULL REFERENCES batches(id),
 PRIMARY KEY(source,request_key));
"""


class MarketCatalog:
    pass
