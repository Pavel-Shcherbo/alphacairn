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

    def test_future_publication_also_blocks_recorded_clock(self):
        self.ingest([bar(published="2099-01-01T00:00:00Z")])
        self.assertEqual(
            self.db.snapshot(query("2098-01-01T00:00:00Z", clock="recorded"))[
                "records"
            ],
            [],
        )

    def test_retraction_does_not_resurrect_old_bar(self):
        self.ingest([bar()])
        withdrawn = bar(published="2020-01-04T00:00:00Z")
        withdrawn["status"] = "retracted"
        for key in ["open", "close", "high", "low", "volume"]:
            withdrawn[key] = None
        self.ingest([withdrawn], key="withdraw")
        self.assertEqual(len(self.db.snapshot(query())["records"]), 1)
        self.assertEqual(self.db.snapshot(query("2020-01-06T00:00:00Z"))["records"], [])
        self.assertEqual(len(self.db.history("demo", "bar", "STOCK-A")["items"]), 2)

    def test_bad_batch_is_atomic_and_idempotency_conflict_is_rejected(self):
        first = self.ingest([bar()])
        self.assertTrue(self.ingest([bar()])["reused"])
        self.assertEqual(
            first["recorded_at"], self.ingest([bar()], key="other")["recorded_at"]
        )
        with self.assertRaises(ValueError):
            self.ingest([bar(close="11")])
        with self.assertRaises(ValueError):
            self.ingest([bar("2020-01-03"), bar(close="12")], key="conflict")
        self.assertEqual(len(self.db.batches("demo")["items"]), 1)
        self.assertEqual(len(self.db.snapshot(query())["records"]), 1)

    def test_exact_numbers_clocks_and_unknown_fields(self):
        controls = [
            dict(close="NaN"),
            dict(high="9"),
            dict(low="11"),
            dict(volume="-1"),
            dict(open=10.0),
            dict(opened_at="2020-01-02T16:00:00Z"),
            dict(published_at="2020-01-02T15:00:00Z"),
            dict(closed_at="2020-01-02T16:00:00"),
            dict(extra=1),
            dict(session="20200102"),
        ]
        for changed in controls:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                observation("bar", {**bar(), **changed})
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(
                observation("bar", {**bar(), "close": "10.123456789"})["close"],
                "10.123456789",
            )
        shifted = observation(
            "bar", {**bar(), "published_at": "2020-01-02T19:01:00+03:00"}
        )
        self.assertEqual(shifted["published_at"], "2020-01-02T16:01:00.000000+00:00")

