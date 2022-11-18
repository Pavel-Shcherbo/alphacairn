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

