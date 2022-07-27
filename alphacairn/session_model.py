"""Normalize operator schedules; materialize and replay bounded UTC sessions."""

import copy
import datetime as dt
import re

from .instruments import identity, timestamp_text
from .market_model import canonical, digest
from .session_zones import decode_zone, load_zone, zone_key

FORMAT = "alphacairn.session-calendar.v1"
MAX_BYTES = 8 * 1024 * 1024


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError(f"{label} fields do not match contract")


