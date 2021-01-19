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

    @contextmanager
    def _transaction(self):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def ingest(self, source, kind, raw, *, request_key):
        source = identifier(source, "source")
        request_key = identifier(request_key, "request_key")
        if kind not in {"bar", "membership"}:
            raise ValueError("kind must be bar or membership")
        rows = decode(raw)
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
            raise ValueError("a batch requires between 1 and 100,000 observations")
        normalized = [observation(kind, row) for row in rows]
        identities = [
            (record_key(kind, row), row["published_at"]) for row in normalized
        ]
        if len(set(identities)) != len(identities):
            raise ValueError(
                "duplicate observation identity/publication within one batch"
            )
        raw_sha = hashlib.sha256(raw).hexdigest()
        normalized_sha = digest(normalized)
        batch_id = digest([source, kind, raw_sha, normalized_sha])
        recorded = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with self._transaction() as db:
            prior = db.execute(
                "SELECT batch_id FROM imports WHERE source=? AND request_key=?",
                (source, request_key),
            ).fetchone()
            if prior and prior["batch_id"] != batch_id:
                raise ValueError("request key was already used for different input")
            existing = db.execute(
                "SELECT * FROM batches WHERE id=?", (batch_id,)
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)",
                    (
                        batch_id,
                        source,
                        kind,
                        recorded,
                        raw_sha,
                        raw,
                        len(normalized),
                        normalized_sha,
                    ),
                )
                for row, (key, published) in zip(normalized, identities):
                    row_sha = digest(row)
                    prior_row = db.execute(
                        "SELECT sha256 FROM observations WHERE source=? AND kind=? AND identity=? AND published_at=?",
                        (source, kind, key, published),
                    ).fetchone()
                    if prior_row:
                        if prior_row["sha256"] != row_sha:
                            raise ValueError(
                                "conflicting values at the same publication time; use a new revision time"
                            )
                        continue
                    effective = row["session"] if kind == "bar" else row["valid_from"]
                    db.execute(
                        "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            source,
                            kind,
                            key,
                            published,
                            batch_id,
                            row["instrument"],
                            effective,
                            canonical(row).decode(),
                            row_sha,
                        ),
                    )
            db.execute(
                "INSERT OR IGNORE INTO imports VALUES(?,?,?)",
                (source, request_key, batch_id),
            )
            result = dict(
                db.execute(
                    "SELECT id,source,kind,recorded_at,raw_sha256,row_count,normalized_sha256 FROM batches WHERE id=?",
                    (batch_id,),
                ).fetchone()
            )
            result["reused"] = existing is not None
            return result

    def ingest_file(self, source, kind, path, *, request_key):
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        return self.ingest(source, kind, raw, request_key=request_key)

    def batches(self, source, *, after="", limit=100):
        source = identifier(source, "source")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("batch page limit must be between 1 and 1000")
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,kind,recorded_at,raw_sha256,row_count,normalized_sha256 FROM batches WHERE source=? AND id>? ORDER BY id LIMIT ?",
                (source, after, limit + 1),
            ).fetchall()
        return {
            "items": [dict(row) for row in rows[:limit]],
            "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

