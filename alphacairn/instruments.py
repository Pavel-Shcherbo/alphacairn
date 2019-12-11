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

    @classmethod
    def compile(cls, definition, currencies):
        allowed = {
            "id",
            "symbol",
            "venue",
            "kind",
            "quote_currency",
            "quantity_step",
            "price_tick",
            "active_from",
            "active_until",
        }
        if not isinstance(definition, dict) or set(definition) - allowed:
            raise ValueError("instrument contains unsupported fields")
        name = identity(definition.get("id"), "instrument ID")
        symbol = identity(definition.get("symbol"), "instrument symbol")
        venue = identity(definition.get("venue"), "instrument venue")
        kind = definition.get("kind")
        if kind not in ("equity", "crypto_spot"):
            raise ValueError("only equity and crypto_spot instruments are supported")
        currency = definition.get("quote_currency")
        if not isinstance(currency, str) or currency not in currencies:
            raise ValueError("quote currency must be declared by the account")
        quantity_step = decimal_value(
            definition.get("quantity_step"), "quantity_step", positive=True
        )
        price_tick = decimal_value(
            definition.get("price_tick"), "price_tick", positive=True
        )
        start = (
            timestamp(definition["active_from"])
            if "active_from" in definition
            else None
        )
        end = (
            timestamp(definition["active_until"])
            if "active_until" in definition
            else None
        )
        if start is not None and end is not None and start >= end:
            raise ValueError("instrument active interval must be non-empty")
        return cls(
            name, symbol, venue, kind, currency, quantity_step, price_tick, start, end
        )

    def require_active(self, when):
        if (
            self.active_from is not None
            and when < self.active_from
            or self.active_until is not None
            and when >= self.active_until
        ):
            raise ValueError("event falls outside the instrument active interval")

