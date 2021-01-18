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
    def __init__(self, database, *, create=False):
        self.path = Path(database).expanduser()
        if self.path.is_symlink():
            raise ValueError("market database must not be a symbolic link")
        if not create and not self.path.is_file():
            raise ValueError("market database does not exist; initialize it explicitly")
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1} or version == 0 and not create:
                raise ValueError("unsupported market database schema")
            if version == 0:
                db.execute("BEGIN IMMEDIATE")
                try:
                    # Another initializer may have committed while we waited.
                    version = db.execute("PRAGMA user_version").fetchone()[0]
                    if version not in {0, 1}:
                        raise ValueError("unsupported market database schema")
                    if version == 0:
                        if db.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        ).fetchone():
                            raise ValueError(
                                "refusing to initialize an unrelated SQLite database"
                            )
                        for statement in SCHEMA.split(";"):
                            if statement.strip():
                                db.execute(statement)
                        db.execute("PRAGMA user_version=1")
                        self.path.chmod(0o600)
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise

            # WAL mode changes can report BUSY immediately during cold starts,
            # even with a busy timeout. Retry only this reversible pragma.
            deadline = time.monotonic() + 10
            while True:
                try:
                    db.execute("PRAGMA journal_mode=WAL").fetchone()
                    break
                except sqlite3.OperationalError as error:
                    if (
                        getattr(error, "sqlite_errorcode", None)
                        not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                        or time.monotonic() >= deadline
                    ):
                        raise
                    time.sleep(0.02)

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db

