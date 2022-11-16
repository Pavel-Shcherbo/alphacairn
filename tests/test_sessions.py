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


