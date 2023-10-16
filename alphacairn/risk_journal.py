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


