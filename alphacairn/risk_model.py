"""Bounded risk-study declarations and synchronous operator-supplied history."""

import copy
from fractions import Fraction

from .instruments import identity, timestamp, timestamp_text
from .market_model import canonical
from .money import decimal_value, text

MAX_INPUT = 16 * 1024 * 1024
MAX_FACTORS = 24
MAX_POINTS = 1001


def bounded_json(value, maximum=MAX_INPUT):
    try:
        raw = canonical(value)
    except (TypeError, RecursionError) as error:
        raise ValueError(
            "risk JSON cannot be serialized within its structure budget"
        ) from error
    if len(raw) > maximum:
        raise ValueError("risk JSON exceeds byte budget")
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 35 or nodes > 500000:
            raise ValueError("risk JSON exceeds structure budget")
        if isinstance(item, dict):
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
    return value


def number(value, label, *, positive=False, nonnegative=False):
    return text(decimal_value(value, label, positive=positive, nonnegative=nonnegative))


def ratio(value, label):
    result = decimal_value(value, label, nonnegative=True)
    if result > 1:
        raise ValueError(label + " must lie between zero and one")
    return text(result)


