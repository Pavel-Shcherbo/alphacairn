"""Canonical market observations with explicit event and publication clocks."""

import hashlib
import json
import re
from datetime import date, datetime, timezone

from .money import decimal_value, text

MAX_ROWS = 100_000
MAX_BYTES = 16 * 1024 * 1024


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}", value
    ):
        raise ValueError(
            f"{label} must be an explicit identifier of at most 96 characters"
        )
    return value


def instant(value, label="timestamp"):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError(f"{label} requires an ISO timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is not an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} requires a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def day(value, label="session"):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{label} requires YYYY-MM-DD")
    result = date.fromisoformat(value).isoformat()
    if result != value:
        raise ValueError(f"{label} requires YYYY-MM-DD")
    return result


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pairs(items):
    output = {}
    for key, value in items:
        if key in output:
            raise ValueError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


