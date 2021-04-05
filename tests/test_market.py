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

    def test_duplicate_json_and_duplicate_rows_rejected(self):
        with self.assertRaises(ValueError):
            self.db.ingest(
                "demo",
                "bar",
                b'[{"instrument":"A","instrument":"B"}]',
                request_key="bad",
            )
        with self.assertRaises(ValueError):
            self.ingest([bar(), bar()])
        self.assertEqual(self.db.batches("demo")["items"], [])

    def test_sources_are_never_silently_combined(self):
        self.ingest([bar()])
        self.ingest([bar(close="20")], source="alternate")
        self.assertEqual(
            self.db.snapshot(query())["records"][0]["observation"]["close"], "10"
        )
        other = query()
        other["source"] = "alternate"
        self.assertEqual(
            self.db.snapshot(other)["records"][0]["observation"]["close"], "20"
        )

    def test_membership_delisting_and_revisions(self):
        self.ingest([member(), member("FAILED", until="2020-01-04")], kind="membership")

        def members(on, cutoff):
            snap = self.db.snapshot(
                {
                    "kind": "membership",
                    "source": "demo",
                    "universe": "TEST",
                    "on": on,
                    "known_at": cutoff,
                    "clock": "published",
                }
            )
            return {x["observation"]["instrument"] for x in snap["records"]}

        self.assertEqual(
            members("2020-01-03", "2020-01-03T12:00:00Z"), {"STOCK-A", "FAILED"}
        )
        self.assertEqual(members("2020-01-04", "2020-01-04T12:00:00Z"), {"STOCK-A"})
        self.ingest(
            [member(until="2020-01-03", published="2020-01-06T12:00:00Z")],
            kind="membership",
            key="late-delisting",
        )
        self.assertEqual(members("2020-01-04", "2020-01-04T12:00:00Z"), {"STOCK-A"})
        self.assertEqual(members("2020-01-04", "2020-01-07T12:00:00Z"), set())

    def test_overlapping_memberships_fail_explicitly(self):
        self.ingest([member(), member(start="2020-01-02")], kind="membership")
        with self.assertRaisesRegex(ValueError, "overlapping"):
            self.db.snapshot(
                {
                    "kind": "membership",
                    "source": "demo",
                    "universe": "TEST",
                    "on": "2020-01-03",
                    "known_at": "2020-01-03T12:00:00Z",
                    "clock": "published",
                }
            )

    def test_decision_features_use_each_time_and_keep_failed_members(self):
        self.ingest([member(), member("NO-DATA")], kind="membership")
        self.ingest([bar(), bar("2020-01-03", close="20")], key="bars")
        args = dict(
            source="demo",
            universe="TEST",
            decisions=[
                {"at": "2020-01-02T17:00:00Z", "session": "2020-01-02"},
                {"at": "2020-01-03T17:00:00Z", "session": "2020-01-03"},
            ],
            start="2020-01-01",
            lookback=2,
            clock="published",
        )
        before = decision_windows(self.db, **args)
        self.ingest(
            [bar(close="30", published="2020-01-04T12:00:00Z")], key="correction"
        )
        self.assertEqual(before, decision_windows(self.db, **args))
        features = {f["instrument"]: f for f in before["windows"][1]["features"]}
        self.assertEqual(features["STOCK-A"]["mean_close"], "15")
        self.assertTrue(features["STOCK-A"]["above_mean"])
        self.assertFalse(features["NO-DATA"]["ready"])
        self.assertIsNone(features["NO-DATA"]["mean_close"])
        self.assertFalse(before["windows"][0]["features"][-1]["ready"])

    def test_read_view_remains_consistent_across_concurrent_revision(self):
        self.ingest([bar()])
        q = query("2020-01-06T00:00:00Z")
        with self.db.read_view() as view:
            first = view.snapshot(q)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(
                    self.ingest,
                    [bar(close="20", published="2020-01-04T12:00:00Z")],
                    key="revision",
                ).result(timeout=10)
            self.assertEqual(view.snapshot(q), first)
        self.assertEqual(
            self.db.snapshot(q)["records"][0]["observation"]["close"], "20"
        )

    def test_concurrent_identical_imports_are_one_batch(self):
        def load(_):
            return MarketCatalog(self.db.path).ingest(
                "demo", "bar", canonical([bar()]), request_key="same"
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(load, range(8)))
        self.assertEqual(len({r["id"] for r in results}), 1)
        self.assertEqual(sum(not r["reused"] for r in results), 1)
        self.assertTrue(self.db.audit()["passed"])

