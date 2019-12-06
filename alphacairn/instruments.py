"""Stable instrument identities and local account denomination contracts."""

import datetime as dt
import re
from dataclasses import dataclass

from .money import arithmetic, decimal_value, text, quantum

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
CURRENCY = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")


def identity(value, label):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a bounded stable identifier")
    return value


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("timestamp requires bounded ISO text with a UTC offset")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp requires an explicit UTC offset")
        return parsed.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError) as error:
        raise ValueError("invalid or out-of-range UTC timestamp") from error


def timestamp_text(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Instrument:
    id: str
    symbol: str
    venue: str
    kind: str
    quote_currency: str
    quantity_step: object
    price_tick: object
    active_from: object = None
    active_until: object = None

