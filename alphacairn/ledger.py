"""Transactional, append-only local portfolio journal with FIFO position lots."""

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .instruments import AccountSpec, identity, timestamp, timestamp_text
from .money import arithmetic, ZERO, aligned, decimal_value, exact_amount, rounded, text

SCHEMA_VERSION = 1
MAX_BATCH = 10000


def canonical(value):
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(
            "journal data must contain bounded finite JSON values"
        ) from error
    if len(payload.encode()) > 2 * 1024 * 1024:
        raise ValueError("journal object exceeds 2 MiB")
    return payload


def digest(payload):
    return hashlib.sha256(payload.encode()).hexdigest()


def normalize_event(event, spec):
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    name = identity(event.get("id"), "event ID")
    when = timestamp(event.get("timestamp"))
    kind = event.get("kind")
    signatures = {
        "deposit": {"currency", "amount"},
        "withdraw": {"currency", "amount"},
        "trade": {"instrument", "side", "quantity", "price", "fee"},
        "split": {"instrument", "numerator", "denominator"},
        "dividend": {"instrument", "gross", "withholding"},
        "fx": {"from_currency", "to_currency", "amount", "rate", "fee"},
    }
    if (
        not isinstance(kind, str)
        or kind not in signatures
        or set(event) - ({"id", "timestamp", "kind"} | signatures[kind])
    ):
        raise ValueError("event contains an unsupported kind or field")
    result = {"id": name, "timestamp": timestamp_text(when), "kind": kind}
    with arithmetic():
        if kind in ("deposit", "withdraw"):
            currency = event.get("currency")
            places = spec.places(currency)
            result.update(
                currency=currency,
                amount=text(exact_amount(event.get("amount"), places, positive=True)),
            )
        elif kind in ("trade", "split", "dividend"):
            instrument = spec.instrument(event.get("instrument"))
            places = spec.places(instrument.quote_currency)
            result["instrument"] = instrument.id
            if kind != "dividend":
                instrument.require_active(when)
            if kind == "trade":
                side = event.get("side")
                if side not in ("buy", "sell"):
                    raise ValueError("trade side must be buy or sell")
                quantity = aligned(
                    event.get("quantity"), instrument.quantity_step, "quantity"
                )
                price = aligned(event.get("price"), instrument.price_tick, "price")
                fee = exact_amount(
                    event.get("fee", "0"), places, "fee", nonnegative=True
                )
                result.update(
                    side=side,
                    quantity=text(quantity.normalize()),
                    price=text(price.normalize()),
                    fee=text(fee),
                )
            elif kind == "split":
                numerator, denominator = event.get("numerator"), event.get(
                    "denominator"
                )
                if (
                    any(
                        type(value) is not int or not 1 <= value <= 1000000
                        for value in (numerator, denominator)
                    )
                    or numerator == denominator
                ):
                    raise ValueError(
                        "split requires distinct positive integer ratio terms up to one million"
                    )
                result.update(numerator=numerator, denominator=denominator)
            else:
                gross = exact_amount(
                    event.get("gross"), places, "gross dividend", positive=True
                )
                withholding = exact_amount(
                    event.get("withholding", "0"),
                    places,
                    "withholding",
                    nonnegative=True,
                )
                if withholding > gross:
                    raise ValueError("dividend withholding exceeds gross income")
                result.update(gross=text(gross), withholding=text(withholding))
        else:
            origin, target = event.get("from_currency"), event.get("to_currency")
            if origin == target:
                raise ValueError("FX currencies must differ")
            origin_places, target_places = spec.places(origin), spec.places(target)
            amount = exact_amount(event.get("amount"), origin_places, positive=True)
            fee = exact_amount(
                event.get("fee", "0"), origin_places, "fee", nonnegative=True
            )
            rate = decimal_value(event.get("rate"), "FX rate", positive=True)
            if rounded(amount * rate, target_places) <= 0:
                raise ValueError("FX proceeds round to zero")
            result.update(
                from_currency=origin,
                to_currency=target,
                amount=text(amount),
                fee=text(fee),
                rate=text(rate.normalize()),
            )
    canonical(result)
    return result


class Ledger:
    pass
