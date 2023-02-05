"""Clock, coverage and offline controls against hand-calculated session instants."""

import base64
import copy
import datetime as dt
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_export import write_execution, verify_execution_bundle
from alphacairn.execution_model import compile_execution
from alphacairn.market_model import canonical, digest
from alphacairn.session_calendar import SessionCalendar
from alphacairn.session_model import build_calendar, verify_calendar
from alphacairn.session_zones import check_tzif, zone_key
from test_execution import scenario, bar
from test_strategy import load
from alphacairn.strategy_inputs import capture_strategy
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_bundle import write_strategy, verify_strategy_bundle
from alphacairn.market_store import MarketCatalog


def endpoint(time, offset=0, fold=None):
    return {"time": time, "day_offset": offset, "fold": fold}


def window(start="09:00", end="17:00", close_offset=0):
    return {"open": endpoint(start), "close": endpoint(end, close_offset)}


def schedule(zone="UTC", start="2019-12-30", end="2020-01-07"):
    return {
        "version": 1,
        "source": "Synthetic operator control; no exchange holiday claims",
        "starts_on": start,
        "ends_on": end,
        "calendars": [
            {
                "id": "demo",
                "timezone": zone,
                "weekdays": [0, 1, 2, 3, 4],
                "segments": [window()],
                "exceptions": [
                    {
                        "session": "2020-01-01",
                        "segments": [],
                        "reason": "control closure",
                    }
                ],
            }
        ],
        "instruments": {"A": "demo"},
    }


def dated(zone, start, end):
    value = schedule(zone, start, end)
    value["calendars"][0]["exceptions"] = []
    value["calendars"][0]["weekdays"] = list(range(7))
    return value


def rehash(value):
    value["sha256"] = digest(
        {key: item for key, item in value.items() if key != "sha256"}
    )


def execution():
    value = scenario()
    value.update(
        version=2,
        calendar=build_calendar(schedule()),
        calendar_policy={"require_all_sessions": True},
    )
    value["ends_at"] = "2020-01-04T00:00:00Z"
    value["bars"] = [bar(2), bar(3)]
    return value


class SessionTests(unittest.TestCase):
    def test_closed_and_exception_open_weekend(self):
        value = schedule()
        value["calendars"][0]["exceptions"].append(
            {
                "session": "2020-01-04",
                "segments": [window("10:00", "12:00")],
                "reason": "special control opening",
            }
        )
        index = SessionCalendar(build_calendar(value))
        self.assertEqual(index.session("demo", "2020-01-01")["segments"], [])
        self.assertEqual(
            index.session("demo", "2020-01-04")["segments"][0]["closes_at"],
            "2020-01-04T12:00:00.000000Z",
        )
        self.assertEqual(index.session("demo", "2020-01-05")["segments"], [])

    def test_early_close_and_midday_break_boundaries(self):
        value = schedule()
        value["calendars"][0]["exceptions"].append(
            {
                "session": "2020-01-03",
                "segments": [window("09:00", "12:00"), window("13:00", "15:00")],
                "reason": "split short control",
            }
        )
        index = SessionCalendar(build_calendar(value))
        self.assertIsNone(index.locate("demo", "2020-01-03T12:00:00Z"))
        self.assertEqual(
            index.next_open("demo", "2020-01-03T12:30:00Z")["opens_at"],
            "2020-01-03T13:00:00.000000Z",
        )
        self.assertIsNone(index.locate("demo", "2020-01-03T15:00:00Z"))
        self.assertIsNotNone(index.locate("demo", "2020-01-03T13:00:00Z"))

    def test_next_open_exclusive_and_session_offsets(self):
        index = SessionCalendar(build_calendar(schedule()))
        self.assertEqual(
            index.next_open("demo", "2020-01-03T09:00:00Z")["session"], "2020-01-03"
        )
        self.assertEqual(
            index.next_open("demo", "2020-01-03T09:00:00Z", inclusive=False)["session"],
            "2020-01-06",
        )
        self.assertEqual(
            index.advance("demo", "2020-01-03", 1)["session"], "2020-01-06"
        )
        self.assertEqual(
            index.advance("demo", "2020-01-04", 1, roll="preceding")["session"],
            "2020-01-06",
        )
        self.assertEqual(
            index.advance("demo", "2020-01-04", -1, roll="following")["session"],
            "2020-01-03",
        )
        with self.assertRaisesRegex(ValueError, "closed"):
            index.advance("demo", "2020-01-04", 0)

    def test_horizon_queries_do_not_extrapolate(self):
        index = SessionCalendar(build_calendar(schedule()))
        for call in (
            lambda: index.next_open("demo", "2020-01-08T00:00:00Z"),
            lambda: index.advance("demo", "2020-01-07", 1),
            lambda: index.session("demo", "2019-12-29"),
            lambda: index.locate("unknown", "2020-01-03T12:00:00Z"),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_dst_spring_shift_changes_utc_not_local_clock(self):
        value = dated("America/New_York", "2020-03-06", "2020-03-10")
        index = SessionCalendar(build_calendar(value))
        self.assertEqual(
            index.session("demo", "2020-03-07")["segments"][0]["opens_at"],
            "2020-03-07T14:00:00.000000Z",
        )
        self.assertEqual(
            index.session("demo", "2020-03-08")["segments"][0]["opens_at"],
            "2020-03-08T13:00:00.000000Z",
        )

    def test_nonexistent_local_clock_rejected_even_with_fold(self):
        for fold in (None, 0, 1):
            value = dated("America/New_York", "2020-03-08", "2020-03-08")
            value["calendars"][0]["segments"] = [window("02:30", "04:00")]
            value["calendars"][0]["segments"][0]["open"]["fold"] = fold
            with self.assertRaisesRegex(ValueError, "nonexistent"):
                build_calendar(value)

    def test_ambiguous_fold_requires_choice_and_has_two_instants(self):
        value = dated("America/New_York", "2020-11-01", "2020-11-01")
        value["calendars"][0]["segments"] = [window("01:30", "03:00")]
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            build_calendar(value)
        results = []
        for fold in (0, 1):
            value["calendars"][0]["segments"][0]["open"]["fold"] = fold
            results.append(
                build_calendar(value)["sessions"][0]["segments"][0]["opens_at"]
            )
        self.assertEqual(
            results, ["2020-11-01T05:30:00.000000Z", "2020-11-01T06:30:00.000000Z"]
        )

    def test_crypto_24_hours_across_dst_is_23_or_25_hours(self):
        for label, hours in (("2020-03-08", 23), ("2020-11-01", 25)):
            value = dated("America/New_York", label, label)
            value["calendars"][0]["segments"] = [window("00:00", "00:00", 1)]
            row = build_calendar(value)["sessions"][0]["segments"][0]
            elapsed = dt.datetime.fromisoformat(
                row["closes_at"].replace("Z", "+00:00")
            ) - dt.datetime.fromisoformat(row["opens_at"].replace("Z", "+00:00"))
            self.assertEqual(elapsed.total_seconds(), hours * 3600)

    def test_overnight_label_and_neighboring_horizon(self):
        value = dated("UTC", "2020-01-01", "2020-01-03")
        value["calendars"][0]["segments"] = [window("22:00", "06:00", 1)]
        index = SessionCalendar(build_calendar(value))
        self.assertEqual(
            index.locate("demo", "2020-01-02T05:00:00Z")["session"], "2020-01-01"
        )
        with self.assertRaisesRegex(ValueError, "neighboring"):
            index.locate("demo", "2020-01-01T05:00:00Z")

    def test_overlapping_and_reversed_windows_rejected(self):
        for windows in (
            [window("17:00", "09:00")],
            [window("09:00", "15:00"), window("14:00", "17:00")],
            [window("09:00", "10:00", 1)],
        ):
            value = schedule()
            value["calendars"][0]["segments"] = windows
            with self.assertRaisesRegex(ValueError, "overlap|reverse"):
                build_calendar(value)

    def test_offline_replay_does_not_read_system_timezone(self):
        document = build_calendar(schedule("America/New_York"))
        with patch(
            "alphacairn.session_model.load_zone",
            side_effect=AssertionError("live timezone read"),
        ):
            rebuilt, _ = verify_calendar(document)
        self.assertEqual(rebuilt, document)

    def test_rehashed_forged_sessions_fail_regeneration(self):
        document = build_calendar(schedule())
        document["sessions"][0]["segments"][0][
            "opens_at"
        ] = "2019-12-30T10:00:00.000000Z"
        rehash(document)
        with self.assertRaisesRegex(ValueError, "regenerated"):
            verify_calendar(document)

    def test_timezone_hash_inventory_and_tzif_bounds(self):
        original = build_calendar(schedule())
        for mutate in (
            lambda d: d["zones"][0].update(sha256="0" * 64),
            lambda d: d["zones"].append(d["zones"][0]),
            lambda d: d["zones"][0].update(tzif_base64="!!!!"),
        ):
            document = copy.deepcopy(original)
            mutate(document)
            rehash(document)
            with self.assertRaises(ValueError):
                verify_calendar(document)
        raw = bytearray(base64.b64decode(original["zones"][0]["tzif_base64"]))
        struct.pack_into(">I", raw, 32, 0x7FFFFFFF)
        with self.assertRaisesRegex(ValueError, "counts"):
            check_tzif(bytes(raw))
        with self.assertRaises(ValueError):
            check_tzif(b"TZif")

    def test_strict_schema_and_safe_zone_paths(self):
        mutations = [
            lambda d: d.update(version=True),
            lambda d: d.update(ends_on="2040-01-01"),
            lambda d: d["calendars"][0].update(weekdays=[True]),
            lambda d: d["calendars"][0]["segments"][0]["open"].update(fold=True),
            lambda d: d["calendars"][0]["segments"][0]["open"].update(time="24:00"),
            lambda d: d["instruments"].update(A="absent"),
            lambda d: d["calendars"][0]["exceptions"].append(
                d["calendars"][0]["exceptions"][0]
            ),
        ]
        for mutate in mutations:
            value = schedule()
            mutate(value)
            with self.assertRaises(ValueError):
                build_calendar(value)
        for key in ("/etc/passwd", "../UTC", "US//Eastern", "UTC\n"):
            with self.assertRaises(ValueError):
                zone_key(key)

    def test_v2_complete_execution_and_legacy_results_match(self):
        value = execution()
        report = simulate_execution(value)
        self.assertTrue(report["calendar_validation"]["complete"])
        self.assertEqual(report["calendar_validation"]["expected_sessions"], 2)
        self.assertEqual(report["cash"], {"USD": "50.00"})
        legacy = copy.deepcopy(value)
        legacy["version"] = 1
        del legacy["calendar"], legacy["calendar_policy"]
        old = simulate_execution(legacy)
        for key in (
            "cash",
            "fills",
            "positions",
            "events",
            "ledger_events",
            "valuation",
        ):
            self.assertEqual(old[key], report[key])
        self.assertNotIn("calendar_validation", old)

    def test_missing_bars_strict_or_explicit_incomplete(self):
        value = execution()
        value["bars"].pop()
        with self.assertRaisesRegex(ValueError, "missing bars"):
            compile_execution(value)
        value["calendar_policy"]["require_all_sessions"] = False
        report = simulate_execution(value)["calendar_validation"]
        self.assertEqual(
            report["missing_sample"], [{"instrument": "A", "session": "2020-01-03"}]
        )
        self.assertFalse(report["complete"])

    def test_closed_session_or_misaligned_envelope_rejected(self):
        for change in (
            lambda d: d["bars"].append(bar(1)),
            lambda d: d["bars"][0].update(closed_at="2020-01-02T16:00:00Z"),
            lambda d: d["calendar"]["definition"]["instruments"].clear(),
        ):
            value = execution()
            change(value)
            with self.assertRaises(ValueError):
                compile_execution(value)

    def test_short_sessions_and_breaks_allow_only_full_bar_envelope(self):
        value = execution()
        source = schedule()
        source["calendars"][0]["exceptions"].append(
            {
                "session": "2020-01-03",
                "segments": [window("09:00", "12:00"), window("13:00", "15:00")],
                "reason": "short split",
            }
        )
        value["calendar"] = build_calendar(source)
        value["bars"][1]["closed_at"] = "2020-01-03T15:00:00Z"
        self.assertTrue(simulate_execution(value)["calendar_validation"]["complete"])
        value["bars"][1]["opened_at"] = "2020-01-03T13:00:00Z"
        with self.assertRaisesRegex(ValueError, "full declared"):
            compile_execution(value)

    def test_execution_horizon_and_partial_active_sessions_fail(self):
        value = execution()
        value["ends_at"] = "2020-02-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "horizon"):
            compile_execution(value)
        value = execution()
        value["bars"].pop()
        value["ends_at"] = "2020-01-03T12:00:00Z"
        with self.assertRaisesRegex(ValueError, "cuts"):
            compile_execution(value)
        value = execution()
        value["bars"].pop(0)
        value["account"]["instruments"][0]["active_from"] = "2020-01-02T12:00:00Z"
        value["commands"] = []
        with self.assertRaisesRegex(ValueError, "cuts"):
            compile_execution(value)

    def test_missing_samples_are_bounded_and_bindings_policy_exact(self):
        value = execution()
        for policy in (
            {"require_all_sessions": 1},
            {"require_all_sessions": True, "extra": 1},
        ):
            value["calendar_policy"] = policy
            with self.assertRaisesRegex(ValueError, "policy"):
                compile_execution(value)
        value = execution()
        source = schedule(end="2020-12-31")
        value["calendar"] = build_calendar(source)
        value["ends_at"] = "2020-12-31T23:00:00Z"
        value["calendar_policy"]["require_all_sessions"] = False
        check = simulate_execution(value)["calendar_validation"]
        self.assertGreater(check["missing_sessions"], 100)
        self.assertEqual(len(check["missing_sample"]), 100)
        self.assertTrue(check["sample_truncated"])

    def test_execution_export_replays_embedded_calendar_offline(self):
        value = execution()
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "bundle"
            write_execution(value, simulate_execution(value), bundle)
            with patch(
                "alphacairn.session_model.load_zone",
                side_effect=AssertionError("live read"),
            ):
                self.assertTrue(verify_execution_bundle(bundle)["passed"])

    def test_strategy_v2_template_capture_and_portable_replay(self):
        config = load("strategy-control.json")
        template = config["execution"]
        source = dated("UTC", "2019-12-29", "2020-01-09")
        source["calendars"][0]["segments"] = [window("09:00", "16:00")]
        source["instruments"] = {
            item["id"]: "demo" for item in template["account"]["instruments"]
        }
        template.update(
            version=2,
            calendar=build_calendar(source),
            calendar_policy={"require_all_sessions": False},
        )
        with tempfile.TemporaryDirectory() as root:
            catalog = MarketCatalog(Path(root) / "market.sqlite", create=True)
            for kind, name in (
                ("bar", "strategy-bars.json"),
                ("membership", "strategy-universe.json"),
            ):
                catalog.ingest(
                    config["source"], kind, canonical(load(name)), request_key=kind
                )
            inputs = capture_strategy(catalog, config)
            report = simulate_strategy(inputs)
            self.assertEqual(len(report["execution"]["fills"]), 6)
            write_strategy(inputs, report, Path(root) / "bundle")
            with patch(
                "alphacairn.session_model.load_zone",
                side_effect=AssertionError("live read"),
            ):
                self.assertTrue(verify_strategy_bundle(Path(root) / "bundle")["passed"])

    def test_stock_weekend_closed_crypto_fill_and_independent_equity(self):
        value = load("session-execution.json")
        report = simulate_execution(value)
        self.assertEqual(report["calendar_validation"]["expected_sessions"], 5)
        self.assertTrue(report["calendar_validation"]["complete"])
        self.assertEqual(report["cash"], {"USD": "30.00"})
        self.assertEqual(report["valuation"]["equity"], "107.00")
        self.assertEqual(
            [(row["instrument"], row["session"]) for row in report["fills"]],
            [("A", "2020-01-02"), ("COIN", "2020-01-04")],
        )

    def test_utc_canonical_boundary_time_contract(self):
        for clock in ("24:00", "12:60", "12:00:60", "9:00", "09:00Z"):
            value = schedule()
            value["calendars"][0]["segments"][0]["open"]["time"] = clock
            with self.assertRaises(ValueError):
                build_calendar(value)
        value = schedule()
        value["calendars"][0]["segments"][0]["open"]["time"] = "09:00:00.123456"
        index = SessionCalendar(build_calendar(value))
        self.assertIsNone(index.locate("demo", "2020-01-03T09:00:00.123455Z"))
        self.assertIsNotNone(index.locate("demo", "2020-01-03T09:00:00.123456Z"))

    def test_cli_build_verify_queries_and_create_only_output(self):
        with tempfile.TemporaryDirectory() as root:
            source, target = Path(root) / "schedule.json", Path(root) / "calendar.json"
            source.write_text(json.dumps(schedule()))

            def cli(*args):
                return subprocess.run(
                    [sys.executable, "-m", "alphacairn.sessions", *map(str, args)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )

            self.assertEqual(cli("build", source, "--output", target).returncode, 0)
            original = target.read_bytes()
            self.assertEqual(cli("build", source, "--output", target).returncode, 2)
            self.assertEqual(target.read_bytes(), original)
            self.assertTrue(json.loads(cli("verify", target).stdout)["passed"])
            self.assertEqual(
                json.loads(
                    cli("next-open", target, "demo", "2020-01-04T12:00:00Z").stdout
                )["session"],
                "2020-01-06",
            )
            self.assertEqual(
                json.loads(cli("advance", target, "demo", "2020-01-03", 1).stdout)[
                    "session"
                ],
                "2020-01-06",
            )
            self.assertEqual(
                cli("locate", target, "demo", "2020-01-03T18:00:00Z").stdout.strip(),
                "null",
            )
            self.assertEqual(cli("session", target, "demo", "2030-01-01").returncode, 2)
