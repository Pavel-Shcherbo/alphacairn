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


def decode(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("market input must be bytes no larger than 16 MiB")
    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda v: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid or excessively nested market JSON") from error


def observation(kind, row):
    if not isinstance(row, dict):
        raise ValueError("each observation must be an object")
    common = {"instrument", "published_at", "status"}
    fields = common | (
        {"session", "opened_at", "closed_at", "open", "high", "low", "close", "volume"}
        if kind == "bar"
        else {"universe", "valid_from", "valid_until"}
    )
    if kind not in {"bar", "membership"} or set(row) != fields:
        raise ValueError("observation fields do not match the declared kind")
    result = dict(row)
    result["instrument"] = identifier(row["instrument"], "instrument")
    result["published_at"] = instant(row["published_at"], "published_at")
    if row["status"] not in {"active", "retracted"}:
        raise ValueError("status must be active or retracted")
    if kind == "bar":
        result["session"] = day(row["session"])
        for field in ["opened_at", "closed_at"]:
            result[field] = instant(row[field], field)
        if (
            result["opened_at"] >= result["closed_at"]
            or result["closed_at"] > result["published_at"]
        ):
            raise ValueError("bar clocks require opened_at < closed_at <= published_at")
        numeric = ["open", "high", "low", "close", "volume"]
        if row["status"] == "retracted":
            if any(row[field] is not None for field in numeric):
                raise ValueError("retracted bars must have null numeric fields")
        else:
            numbers = {
                field: decimal_value(
                    row[field],
                    field,
                    positive=field != "volume",
                    nonnegative=field == "volume",
                )
                for field in numeric
            }
            if (
                not numbers["low"]
                <= min(numbers["open"], numbers["close"])
                <= max(numbers["open"], numbers["close"])
                <= numbers["high"]
            ):
                raise ValueError("OHLC prices violate the low/high envelope")
            result.update({field: text(value) for field, value in numbers.items()})
    else:
        result["universe"] = identifier(row["universe"], "universe")
        result["valid_from"] = day(row["valid_from"], "valid_from")
        if row["valid_until"] is not None:
            result["valid_until"] = day(row["valid_until"], "valid_until")
            if result["valid_until"] <= result["valid_from"]:
                raise ValueError(
                    "membership intervals are half-open and must have positive length"
                )
    return result


