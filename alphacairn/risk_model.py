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


def compile_risk(value, spec):
    bounded_json(value, 1024 * 1024)
    fields = {
        "version",
        "name",
        "as_of",
        "max_age_seconds",
        "history_start",
        "history_end",
        "periods_per_year",
        "confidence",
        "shrinkage",
        "min_observations",
        "max_gap_days",
        "concentration_limits",
        "scenarios",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("risk configuration requires the complete version 1 contract")
    result = copy.deepcopy(value)
    result["name"] = identity(value["name"], "risk study name")
    for key in ("as_of", "history_start", "history_end"):
        result[key] = timestamp_text(timestamp(value[key]))
    if not result["history_start"] < result["history_end"] <= result["as_of"]:
        raise ValueError("risk window requires history_start < history_end <= as_of")
    for key, low, high in [
        ("max_age_seconds", 0, 366 * 86400),
        ("periods_per_year", 1, 366),
        ("min_observations", 2, 1000),
        ("max_gap_days", 1, 31),
    ]:
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("invalid risk " + key)
    result["confidence"] = ratio(value["confidence"], "confidence")
    if not 0 < Fraction(result["confidence"]) < 1:
        raise ValueError("confidence must lie strictly between zero and one")
    result["shrinkage"] = ratio(value["shrinkage"], "shrinkage")
    limits = value["concentration_limits"]
    if not isinstance(limits, dict) or set(limits) != {
        "instrument",
        "currency",
        "venue",
        "kind",
    }:
        raise ValueError(
            "concentration limits require instrument, currency, venue and kind"
        )
    result["concentration_limits"] = {
        key: ratio(v, "concentration limit") for key, v in sorted(limits.items())
    }
    scenarios = value["scenarios"]
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 32:
        raise ValueError("risk study requires 1 through 32 stress scenarios")
    ids = set()
    parsed = []
    for item in scenarios:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "price_shocks",
            "fx_shocks",
        }:
            raise ValueError("scenario requires id, price_shocks and fx_shocks")
        label = identity(item["id"], "scenario ID")
        if label in ids:
            raise ValueError("stress scenario IDs must be unique")
        ids.add(label)
        row = {"id": label}
        for key in ("price_shocks", "fx_shocks"):
            if not isinstance(item[key], dict) or len(item[key]) > 1000:
                raise ValueError("scenario shocks require bounded objects")
            row[key] = {}
            for name, shock in sorted(item[key].items()):
                if key == "price_shocks":
                    spec.instrument(name)
                else:
                    spec.places(name)
                    if name == spec.base_currency:
                        raise ValueError("base-currency FX shocks are unsupported")
                change = decimal_value(shock, "relative shock")
                if change < -1 or change > 10 or key == "fx_shocks" and change <= -1:
                    raise ValueError(
                        "price shocks require [-1,10]; FX shocks require (-1,10]"
                    )
                row[key][name] = text(change)
        parsed.append(row)
    result["scenarios"] = parsed
    return result


def compile_history(value, spec):
    bounded_json(value)
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "source", "price_basis", "observations"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["price_basis"] != "split_adjusted_price_only"
    ):
        raise ValueError(
            "history requires version 1, source, split_adjusted_price_only basis and observations"
        )
    source = identity(value["source"], "risk history source")
    points = value["observations"]
    if not isinstance(points, list) or len(points) > MAX_POINTS:
        raise ValueError("risk history supports at most 1,001 observations")
    result = []
    previous = None
    for item in points:
        if not isinstance(item, dict) or set(item) != {
            "at",
            "available_at",
            "prices",
            "fx",
        }:
            raise ValueError("history point requires at, available_at, prices and fx")
        at = timestamp_text(timestamp(item["at"]))
        available = timestamp_text(timestamp(item["available_at"]))
        if available < at or previous is not None and at <= previous:
            raise ValueError(
                "history requires increasing observation times and availability at/after observation"
            )
        previous = at
        row = {"at": at, "available_at": available}
        for key in ("prices", "fx"):
            if not isinstance(item[key], dict) or len(item[key]) > 1000:
                raise ValueError("history values must be bounded objects")
            row[key] = {}
            for name, value in sorted(item[key].items()):
                if key == "prices":
                    spec.instrument(name)
                else:
                    spec.places(name)
                parsed = (
                    None
                    if value is None
                    else number(value, "history " + key, positive=True)
                )
                if (
                    key == "fx"
                    and name == spec.base_currency
                    and parsed is not None
                    and Fraction(parsed) != 1
                ):
                    raise ValueError("base FX history must equal one")
                row[key][name] = parsed
        result.append(row)
    return {
        "version": 1,
        "source": source,
        "price_basis": "split_adjusted_price_only",
        "observations": result,
    }
