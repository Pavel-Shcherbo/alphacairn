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

    @staticmethod
    def _verified_record(record):
        if (
            record["source"] != record["batch_source"]
            or record["kind"] != record["batch_kind"]
            or instant(record["recorded_at"]) != record["recorded_at"]
        ):
            raise ValueError("stored observation batch provenance mismatch")
        payload = decode(record["payload"].encode())
        row = observation(record["kind"], payload)
        if (
            row != payload
            or digest(row) != record["sha256"]
            or record_key(record["kind"], row) != record["identity"]
            or row["published_at"] != record["published_at"]
            or row["instrument"] != record["instrument"]
        ):
            raise ValueError(
                "stored observation failed canonical identity verification"
            )
        effective = row["session"] if record["kind"] == "bar" else row["valid_from"]
        if effective != record["effective"]:
            raise ValueError("stored observation index differs from payload")
        return {
            "observation": row,
            "batch_id": record["batch_id"],
            "recorded_at": record["recorded_at"],
            "observation_sha256": record["sha256"],
        }

    @contextmanager
    def read_view(self):
        """Hold one SQLite read snapshot across related queries."""
        with self._connect() as db:
            db.execute("BEGIN")
            db.execute("SELECT COUNT(*) FROM batches").fetchone()
            yield MarketView(self, db)

    def snapshot(self, query):
        with self.read_view() as view:
            return view.snapshot(query)

    def _snapshot(self, query, db):
        query = validate_query(query)
        parameters = [query["source"], query["kind"], query["known_at"]]
        condition = "o.source=? AND o.kind=? AND o.published_at<=?"
        if query["clock"] == "recorded":
            condition += " AND b.recorded_at<=?"
            parameters.append(query["known_at"])
        if query["kind"] == "bar":
            condition += " AND o.instrument=? AND o.effective>=? AND o.effective<=?"
            parameters.extend([query["instrument"], query["start"], query["end"]])
        else:
            condition += " AND o.effective<=?"
            parameters.append(query["on"])
        # Rank revisions before filtering retractions or membership end dates.
        # Otherwise an obsolete active value could reappear after a withdrawal.
        sql = f"""WITH ranked AS (
          SELECT o.*, b.recorded_at, b.source AS batch_source, b.kind AS batch_kind,
          ROW_NUMBER() OVER(PARTITION BY o.identity ORDER BY o.published_at DESC) AS rank
          FROM observations o JOIN batches b ON b.id=o.batch_id WHERE {condition})
          SELECT * FROM ranked WHERE rank=1 ORDER BY effective,instrument,identity LIMIT ?"""
        rows = db.execute(sql, [*parameters, MAX_ROWS + 1]).fetchall()
        if len(rows) > MAX_ROWS:
            raise ValueError(
                "snapshot exceeds 100,000 candidate records; narrow the query"
            )
        selected = []
        for record in rows:
            item = self._verified_record(record)
            row = item["observation"]
            if row["status"] == "retracted":
                continue
            if query["kind"] == "membership" and (
                row["universe"] != query["universe"]
                or row["valid_until"] is not None
                and row["valid_until"] <= query["on"]
            ):
                continue
            selected.append(item)
        result = {"schema": 1, "query": query, "records": selected}
        result["sha256"] = snapshot_identity(result)
        verify_snapshot(result)
        return result

    def history(self, source, kind, instrument, *, limit=1000):
        source = identifier(source, "source")
        instrument = identifier(instrument, "instrument")
        if (
            kind not in {"bar", "membership"}
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ValueError("invalid history kind or limit")
        with self._connect() as db:
            rows = db.execute(
                "SELECT o.*,b.recorded_at,b.source AS batch_source,b.kind AS batch_kind FROM observations o JOIN batches b ON b.id=o.batch_id WHERE o.source=? AND o.kind=? AND o.instrument=? ORDER BY o.effective,o.published_at LIMIT ?",
                (source, kind, instrument, limit + 1),
            ).fetchall()
        return {
            "items": [self._verified_record(row) for row in rows[:limit]],
            "complete": len(rows) <= limit,
        }

    def audit(self, *, limit=1000):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("audit limit must be between 1 and 1000")
        errors = []
        checked = 0
        processed_rows = 0
        processed_bytes = 0
        allowed_owners = {}
        with self._connect() as db:
            db.execute("BEGIN")
            batches = db.execute(
                "SELECT id,source,kind,recorded_at,raw_sha256,row_count,normalized_sha256 FROM batches ORDER BY id LIMIT ?",
                (limit + 1,),
            ).fetchall()
            complete = len(batches) <= limit
            for batch in batches[:limit]:
                try:
                    raw = bytes(
                        db.execute(
                            "SELECT raw FROM batches WHERE id=?", (batch["id"],)
                        ).fetchone()[0]
                    )
                    processed_bytes += len(raw)
                    if processed_bytes > 64 * 1024 * 1024:
                        complete = False
                        break
                    rows = decode(raw)
                    processed_rows += len(rows) if isinstance(rows, list) else 0
                    if processed_rows > MAX_ROWS:
                        complete = False
                        break
                    if (
                        batch["kind"] not in {"bar", "membership"}
                        or not isinstance(rows, list)
                        or not 1 <= len(rows) <= MAX_ROWS
                    ):
                        raise ValueError("invalid stored batch kind or row count")
                    normalized = [observation(batch["kind"], row) for row in rows]
                    if (
                        len(normalized) != batch["row_count"]
                        or digest(normalized) != batch["normalized_sha256"]
                        or hashlib.sha256(raw).hexdigest() != batch["raw_sha256"]
                        or digest(
                            [
                                batch["source"],
                                batch["kind"],
                                batch["raw_sha256"],
                                batch["normalized_sha256"],
                            ]
                        )
                        != batch["id"]
                    ):
                        raise ValueError("stored raw batch identity mismatch")
                    if instant(batch["recorded_at"]) != batch["recorded_at"]:
                        raise ValueError("noncanonical batch recording time")
                    # An identical observation may first belong to an earlier batch.
                    for row in normalized:
                        key = (
                            batch["source"],
                            batch["kind"],
                            record_key(batch["kind"], row),
                            row["published_at"],
                        )
                        allowed_owners.setdefault(key, set()).add(batch["id"])
                        found = db.execute(
                            "SELECT o.*, b.recorded_at,b.source AS batch_source,b.kind AS batch_kind FROM observations o JOIN batches b ON b.id=o.batch_id WHERE o.source=? AND o.kind=? AND o.identity=? AND o.published_at=?",
                            (
                                batch["source"],
                                batch["kind"],
                                record_key(batch["kind"], row),
                                row["published_at"],
                            ),
                        ).fetchone()
                        if (
                            found is None
                            or self._verified_record(found)["observation"] != row
                        ):
                            raise ValueError(
                                "raw batch and indexed observation disagree"
                            )
                    checked += 1
                except (ValueError, TypeError, KeyError) as error:
                    errors.append({"batch_id": batch["id"], "error": str(error)})
            foreign = db.execute("PRAGMA foreign_key_check").fetchone()
            if foreign:
                errors.append({"error": "foreign key inconsistency"})
            indexed = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            if complete:
                if indexed != len(allowed_owners):
                    errors.append(
                        {
                            "error": "observation index contains missing or extra revisions"
                        }
                    )
                else:
                    for row in db.execute(
                        "SELECT source,kind,identity,published_at,batch_id FROM observations"
                    ):
                        key = (
                            row["source"],
                            row["kind"],
                            row["identity"],
                            row["published_at"],
                        )
                        if row["batch_id"] not in allowed_owners.get(key, set()):
                            errors.append(
                                {
                                    "error": "indexed observation does not belong to its raw batch"
                                }
                            )
                            break
        return {
            "passed": complete and not errors,
            "complete": complete,
            "checked_batches": checked,
            "indexed_revisions": indexed,
            "errors": errors,
        }


class MarketView:
    """Query interface valid only inside MarketCatalog.read_view()."""

    def __init__(self, catalog, database):
        self._catalog = catalog
        self._database = database

    def snapshot(self, query):
        return self._catalog._snapshot(query, self._database)
