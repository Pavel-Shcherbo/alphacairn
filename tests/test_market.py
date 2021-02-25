"""Independent revision timelines, information cutoffs and storage controls."""

import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import localcontext
from pathlib import Path

from alphacairn.market_model import (
    canonical,
    observation,
    snapshot_identity,
    verify_snapshot,
)
from alphacairn.market_store import MarketCatalog
from alphacairn.market_research import decision_windows, read_snapshot, write_snapshot


def bar(session="2020-01-02", close="10", published=None, instrument="STOCK-A"):
    return {
        "instrument": instrument,
        "session": session,
        "opened_at": session + "T09:00:00Z",
        "closed_at": session + "T16:00:00Z",
        "published_at": published or session + "T16:01:00Z",
        "status": "active",
        "open": "10",
        "high": "30",
        "low": "1",
        "close": close,
        "volume": "100",
    }


def member(
    instrument="STOCK-A",
    start="2020-01-01",
    until=None,
    published="2019-12-31T12:00:00Z",
):
    return {
        "instrument": instrument,
        "universe": "TEST",
        "valid_from": start,
        "valid_until": until,
        "published_at": published,
        "status": "active",
    }


def query(known="2020-01-02T17:00:00Z", clock="published"):
    return {
        "kind": "bar",
        "source": "demo",
        "instrument": "STOCK-A",
        "start": "2020-01-01",
        "end": "2020-01-31",
        "known_at": known,
        "clock": clock,
    }


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = MarketCatalog(self.root / "market.sqlite", create=True)

    def ingest(self, rows, kind="bar", key="first", source="demo"):
        return self.db.ingest(source, kind, canonical(rows), request_key=key)

    def test_revisions_use_publication_not_latest_loaded_value(self):
        self.ingest([bar()])
        self.ingest([bar(close="20", published="2020-01-05T10:00:00Z")], key="revision")
        for cutoff, expected in [
            ("2020-01-02T16:00:00Z", []),
            ("2020-01-03T00:00:00Z", ["10"]),
            ("2020-01-06T00:00:00Z", ["20"]),
        ]:
            actual = self.db.snapshot(query(cutoff))
            self.assertEqual(
                [x["observation"]["close"] for x in actual["records"]], expected
            )
        self.assertTrue(self.db.audit()["passed"])

    def test_recorded_clock_refuses_claimed_historical_availability(self):
        loaded = self.ingest([bar()])
        self.assertEqual(self.db.snapshot(query(clock="recorded"))["records"], [])
        current = query(loaded["recorded_at"], clock="recorded")
        self.assertEqual(len(self.db.snapshot(current)["records"]), 1)

