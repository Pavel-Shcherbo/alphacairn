"""Explicit development/holdout windows and frozen research-method identities."""

import copy

from .instruments import identity, timestamp, timestamp_text
from .market_model import canonical, digest
from .risk_inputs import prepare_risk_inputs
from .strategy_inputs import prepare_strategy_inputs

MAX_INPUT = 16 * 1024 * 1024


def declaration(value):
    if (
        not isinstance(value, dict)
        or set(value)
        != {"version", "name", "family", "hypothesis", "development", "holdout"}
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError(
            "study requires version 1, name, family, hypothesis, development and holdout"
        )
    identity(value["name"], "study name")
    if value["family"] not in ("risk", "strategy"):
        raise ValueError("study family must be risk or strategy")
    prose(value["hypothesis"], "hypothesis", 2000)
    result = copy.deepcopy(value)
    for field in ("development", "holdout"):
        window = value[field]
        if not isinstance(window, dict) or set(window) != {"start", "end"}:
            raise ValueError("study windows require start and end")
        start, end = (timestamp(window[k]) for k in ("start", "end"))
        if start >= end:
            raise ValueError("study window start must precede end")
        result[field] = {"start": timestamp_text(start), "end": timestamp_text(end)}
    if result["development"]["end"] >= result["holdout"]["start"]:
        raise ValueError("development must end strictly before the holdout starts")
    return result


def prose(value, label, maximum=500):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(c) < 32 and c != "\n" for c in value)
    ):
        raise ValueError(label + " requires bounded nonempty text")
    return value


def key(value):
    return identity(value, "request key")


