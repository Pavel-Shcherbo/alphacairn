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


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("session label requires YYYY-MM-DD")
    result = dt.date.fromisoformat(value)
    if not 1900 <= result.year <= 2200:
        raise ValueError("calendar dates must be within 1900–2200")
    return result


def bounded_json(value):
    try:
        if len(canonical(value)) > MAX_BYTES:
            raise ValueError("calendar exceeds 8 MiB")
    except (TypeError, RecursionError) as error:
        raise ValueError("calendar requires bounded finite JSON") from error


