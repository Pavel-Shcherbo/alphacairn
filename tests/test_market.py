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

    def test_export_verification_and_no_overwrite(self):
        self.ingest([bar()])
        snap = self.db.snapshot(query())
        path = self.root / "snapshot.json"
        write_snapshot(snap, path)
        self.assertEqual(read_snapshot(path), snap)
        with self.assertRaises(FileExistsError):
            write_snapshot(snap, path)
        invalid_schema = copy.deepcopy(snap)
        invalid_schema["schema"] = True
        invalid_schema["sha256"] = snapshot_identity(invalid_schema)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            verify_snapshot(invalid_schema)
        changed = copy.deepcopy(snap)
        changed["records"][0]["observation"]["close"] = "22"
        with self.assertRaisesRegex(ValueError, "digest"):
            verify_snapshot(changed)
        changed = copy.deepcopy(snap)
        changed["query"]["known_at"] = "2020-01-01T00:00:00.000000+00:00"
        changed["sha256"] = snapshot_identity(changed)
        with self.assertRaisesRegex(ValueError, "cutoff"):
            verify_snapshot(changed)
        link = self.root / "link.json"
        link.symlink_to(path)
        with self.assertRaises(FileExistsError):
            write_snapshot(snap, link)
        self.assertEqual(len(list(self.root.glob(".market-*"))), 0)

    def test_audit_detects_raw_and_index_corruption_and_partial_is_not_pass(self):
        self.ingest([bar()])
        self.ingest([bar("2020-01-03")], key="second")
        self.assertFalse(self.db.audit(limit=1)["passed"])
        self.assertFalse(self.db.audit(limit=1)["complete"])
        with closing(sqlite3.connect(self.db.path)) as db, db:
            db.execute(
                "UPDATE observations SET payload=replace(payload,'100','101') WHERE effective='2020-01-02'"
            )
        with self.assertRaisesRegex(ValueError, "identity"):
            self.db.snapshot(query())
        self.assertFalse(self.db.audit()["passed"])

    def test_pagination_missing_db_and_future_schema(self):
        self.ingest([bar()])
        self.ingest([bar("2020-01-03")], key="second")
        first = self.db.batches("demo", limit=1)
        second = self.db.batches("demo", limit=1, after=first["next_cursor"])
        self.assertEqual(len(first["items"]) + len(second["items"]), 2)
        self.assertIsNone(second["next_cursor"])
        absent = self.root / "absent.sqlite"
        with self.assertRaises(ValueError):
            MarketCatalog(absent)
        self.assertFalse(absent.exists())
        with closing(sqlite3.connect(self.db.path)) as db, db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(ValueError):
            MarketCatalog(self.db.path)

    def test_cli_lifecycle_and_offline_verify_without_database(self):
        source = self.root / "bars.json"
        source.write_bytes(canonical([bar()]))
        q = self.root / "query.json"
        q.write_bytes(canonical(query()))
        out = self.root / "export.json"

        def cli(*args, expected=0):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "alphacairn.market_cli",
                    "--database",
                    str(self.db.path),
                    *map(str, args),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, expected, result.stderr)
            return json.loads(result.stdout) if result.stdout else None

        cli("ingest", "demo", "bar", source, "--request-key", "cli")
        cli("snapshot", q, "--output", out)
        self.assertTrue(cli("verify-snapshot", out)["passed"])
        self.assertTrue(cli("audit")["passed"])
        cli("snapshot", q, "--output", out, expected=2)
        missing = self.root / "never-created.sqlite"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "alphacairn.market_cli",
                "--database",
                str(missing),
                "verify-snapshot",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(missing.exists())

    def test_randomized_revision_selection_against_plain_timeline_oracle(self):
        import random

        rng = random.Random(71)
        timeline = []
        for day_number in range(2, 8):
            for revision in range(3):
                row = bar(
                    f"2020-01-{day_number:02d}",
                    close=str(rng.randint(2, 29)),
                    published=f"2020-01-{day_number+revision:02d}T17:00:00Z",
                )
                timeline.append(row)
        rng.shuffle(timeline)
        for index, row in enumerate(timeline):
            self.ingest([row], key=f"row-{index}")
        for cutoff_day in range(2, 12):
            cutoff = f"2020-01-{cutoff_day:02d}T18:00:00Z"
            eligible = [r for r in timeline if r["published_at"] <= cutoff]
            expected = {}
            for session in sorted({r["session"] for r in eligible}):
                known = [r for r in eligible if r["session"] == session]
                expected[session] = max(known, key=lambda r: r["published_at"])["close"]
            actual = {
                r["observation"]["session"]: r["observation"]["close"]
                for r in self.db.snapshot(query(cutoff))["records"]
            }
            self.assertEqual(actual, expected)

    def test_raw_blob_and_wrong_batch_ownership_detected(self):
        self.ingest([bar()])
        other = self.ingest([bar("2020-01-03")], key="other")
        with closing(sqlite3.connect(self.db.path)) as db, db:
            db.execute(
                "UPDATE observations SET batch_id=? WHERE effective='2020-01-02'",
                (other["id"],),
            )
        self.assertFalse(self.db.audit()["passed"])
        with closing(sqlite3.connect(self.db.path)) as db, db:
            db.execute("UPDATE batches SET raw=? WHERE id=?", (b"[]", other["id"]))
        self.assertFalse(self.db.audit()["passed"])

