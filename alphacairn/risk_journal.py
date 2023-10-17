"""Read-only coherent journal backup and independent accepted-event reconstruction."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from .instruments import AccountSpec
from .ledger import Ledger, digest as ledger_digest
from .market_model import canonical
from .risk_model import bounded_json

MAX_EVENTS = 10000
MAX_DATABASE = 32 * 1024 * 1024


def replay_journal(value):
    bounded_json(value)
    if (
        not isinstance(value, dict)
        or set(value) != {"account", "events", "receipts", "state"}
        or not isinstance(value["events"], list)
        or len(value["events"]) > MAX_EVENTS
        or not isinstance(value["receipts"], list)
        or len(value["receipts"]) != len(value["events"])
    ):
        raise ValueError(
            "risk journal requires account, at most 10,000 accepted events, receipts and state"
        )
    spec = AccountSpec.compile(value["account"])
    with tempfile.TemporaryDirectory(prefix="risk-journal-replay-") as directory:
        ledger = Ledger(Path(directory) / "replay.sqlite", spec.definition())
        receipts = []
        for offset in range(0, len(value["events"]), 1000):
            for receipt in ledger.apply_batch(value["events"][offset : offset + 1000]):
                if receipt.pop("duplicate"):
                    raise ValueError("risk journal contains duplicate accepted events")
                receipts.append(receipt)
        state = ledger.state()
    if canonical(receipts) != canonical(value["receipts"]) or canonical(
        state
    ) != canonical(value["state"]):
        raise ValueError(
            "accepted-event replay differs from retained journal receipts or state"
        )
    return spec, state


def capture_journal(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DATABASE:
        raise ValueError(
            "risk source must be an ordinary journal database no larger than 32 MiB"
        )
    wal = Path(str(path) + "-wal")
    if wal.is_symlink() or wal.exists() and wal.stat().st_size > MAX_DATABASE:
        raise ValueError("risk source WAL is unsafe or exceeds 32 MiB")
    deadline = time.monotonic() + 10
    with tempfile.TemporaryDirectory(prefix="risk-capture-") as directory:
        private = Path(directory) / "capture.sqlite"
        uri = path.resolve().as_uri() + "?mode=ro"
        with (
            closing(
                sqlite3.connect(uri, uri=True, isolation_level=None, timeout=1)
            ) as source,
            closing(sqlite3.connect(private, isolation_level=None)) as target,
        ):
            source.execute("PRAGMA query_only=ON")
            source.execute("BEGIN")
            if (
                source.execute("PRAGMA page_count").fetchone()[0]
                * source.execute("PRAGMA page_size").fetchone()[0]
                > MAX_DATABASE
            ):
                raise ValueError("journal logical database exceeds 32 MiB")

            def progress(*_):
                if time.monotonic() > deadline:
                    raise ValueError(
                        "journal capture exceeded ten-second backup budget"
                    )

            source.backup(target, pages=256, progress=progress, sleep=0.01)
        ledger = Ledger(private)
        with ledger._transaction(write=False) as db:
            history = db.execute(
                "SELECT * FROM events ORDER BY seq LIMIT ?", (MAX_EVENTS + 1,)
            ).fetchall()
            if len(history) > MAX_EVENTS:
                raise ValueError("risk journal capture exceeds 10,000 events")
            events = []
            receipts = []
            for index, row in enumerate(history, 1):
                event = json.loads(row["payload"])
                if (
                    row["seq"] != index
                    or ledger_digest(row["payload"]) != row["payload_sha256"]
                    or event.get("id") != row["event_id"]
                    or event.get("timestamp") != row["timestamp"]
                    or event.get("kind") != row["kind"]
                ):
                    raise ValueError(
                        "source journal accepted-event identity is inconsistent"
                    )
                events.append(event)
                receipts.append(json.loads(row["receipt"]))
            postings = db.execute(
                "SELECT event_seq,currency,account,amount FROM postings ORDER BY id LIMIT 200001"
            ).fetchall()
            if len(postings) > 200000:
                raise ValueError("risk journal capture exceeds 200,000 postings")
            by_sequence = {index: [] for index in range(1, len(history) + 1)}
            for posting in postings:
                if posting["event_seq"] not in by_sequence:
                    raise ValueError("source posting refers to an unknown event")
                by_sequence[posting["event_seq"]].append(
                    {key: posting[key] for key in ("currency", "account", "amount")}
                )
            if any(
                receipt["postings"] != by_sequence[index]
                for index, receipt in enumerate(receipts, 1)
            ):
                raise ValueError("source postings differ from accepted receipts")
            document = {
                "account": ledger.spec.definition(),
                "events": events,
                "receipts": receipts,
                "state": ledger._state(db),
            }
    replay_journal(document)
    return document
