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

