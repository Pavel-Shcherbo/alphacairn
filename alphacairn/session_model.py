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


def segments(value):
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("schedule requires 0–8 segments")
    result = []
    for item in value:
        fields(item, "open close", "segment")
        normalized = {}
        for key in ("open", "close"):
            endpoint = item[key]
            fields(endpoint, "time day_offset fold", "local endpoint")
            clock = endpoint["time"]
            if not isinstance(clock, str) or not re.fullmatch(
                r"\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?", clock
            ):
                raise ValueError("local clock requires HH:MM[:SS[.ffffff]]")
            if (
                int(clock[:2]) > 23
                or int(clock[3:5]) > 59
                or (len(clock) >= 8 and int(clock[6:8]) > 59)
            ):
                raise ValueError("local clock must be 00:00:00 through 23:59:59.999999")
            parsed = dt.time.fromisoformat(clock)
            offset, fold = endpoint["day_offset"], endpoint["fold"]
            if type(offset) is not int or not -2 <= offset <= 2:
                raise ValueError("day offset must be -2 through 2")
            if fold is not None and (type(fold) is not int or fold not in (0, 1)):
                raise ValueError("fold must be null, 0 or 1")
            normalized[key] = {
                "time": parsed.isoformat(timespec="microseconds"),
                "day_offset": offset,
                "fold": fold,
            }
        result.append(normalized)
    return result


