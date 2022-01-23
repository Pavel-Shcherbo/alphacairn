"""Freeze decision-time market vintages separately from execution realizations."""

import copy
from dataclasses import dataclass
from decimal import Decimal

from .execution_model import ExecutionPlan, compile_execution
from .instruments import AccountSpec, timestamp, timestamp_text
from .market_model import (
    MAX_BYTES,
    canonical,
    day,
    digest,
    identifier,
    instant,
    validate_query,
    verify_snapshot,
)
from .money import aligned, arithmetic, decimal_value, text

EXECUTION_FIELDS = {
    "version",
    "account",
    "starts_at",
    "ends_at",
    "initial_cash",
    "fees",
    "slippage_bps",
    "max_mark_age_seconds",
    "fx",
}
CONFIG_FIELDS = {
    "version",
    "source",
    "universe",
    "clock",
    "history_start",
    "lookback",
    "max_feature_age_seconds",
    "decisions",
    "market_cutoff",
    "execution_sessions",
    "execution",
    "liquidity",
    "target_quantities",
    "allocation_order",
    "missing_signal_policy",
}


def compile_strategy(definition):
    try:
        size = len(canonical(definition))
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("strategy requires bounded finite JSON") from error
    if size > 8 * 1024 * 1024:
        raise ValueError("strategy configuration exceeds 8 MiB")
    if (
        not isinstance(definition, dict)
        or set(definition) != CONFIG_FIELDS
        or type(definition["version"]) is not int
        or definition["version"] != 1
    ):
        raise ValueError(
            "strategy requires version 1 and explicit signal/data/execution fields"
        )
    result = copy.deepcopy(definition)
    for key in ("source", "universe"):
        result[key] = identifier(result[key], key)
    if result["clock"] not in ("published", "recorded"):
        raise ValueError("strategy clock must be published or recorded")
    if result["missing_signal_policy"] not in ("hold", "exit"):
        raise ValueError("missing signal policy must be hold or exit")
    if type(result["lookback"]) is not int or not 2 <= result["lookback"] <= 1000:
        raise ValueError("strategy lookback must be between 2 and 1000")
    age = result["max_feature_age_seconds"]
    if type(age) is not int or not 0 <= age <= 366 * 86400:
        raise ValueError("feature age must be an explicit 0–366 day budget")
    execution = result["execution"]
    if not isinstance(execution, dict) or set(execution) != EXECUTION_FIELDS:
        raise ValueError("strategy execution template excludes bars and commands")
    account = AccountSpec.compile(execution["account"])
    if len(account.instruments) > 100:
        raise ValueError("strategy supports at most 100 account instruments")
    execution["account"] = account.definition()
    start, end = timestamp(execution["starts_at"]), timestamp(execution["ends_at"])
    if start >= end:
        raise ValueError("strategy execution start must precede end")
    execution["starts_at"], execution["ends_at"] = timestamp_text(
        start
    ), timestamp_text(end)
    result["history_start"] = day(result["history_start"], "history start")
    result["market_cutoff"] = instant(result["market_cutoff"], "execution data cutoff")
    sessions = result["execution_sessions"]
    if not isinstance(sessions, dict) or set(sessions) != {"start", "end"}:
        raise ValueError("execution sessions require explicit start and end labels")
    sessions = {key: day(value, key) for key, value in sessions.items()}
    if sessions["start"] > sessions["end"]:
        raise ValueError("execution session range is reversed")
    result["execution_sessions"] = sessions
    names = {instrument.id for instrument in account.instruments}
    order = result["allocation_order"]
    if (
        not isinstance(order, list)
        or any(not isinstance(name, str) for name in order)
        or len(order) != len(names)
        or set(order) != names
    ):
        raise ValueError(
            "allocation order must list every account instrument exactly once"
        )
    targets = result["target_quantities"]
    if not isinstance(targets, dict) or set(targets) != names:
        raise ValueError("target quantities must cover every account instrument")
    with arithmetic():
        result["target_quantities"] = {
            name: text(
                aligned(
                    targets[name],
                    account.instrument(name).quantity_step,
                    "target quantity",
                )
            )
            for name in order
        }
    decisions = result["decisions"]
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= 100:
        raise ValueError("strategy requires 1–100 explicit decisions")
    previous, previous_session = None, None
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {"at", "session"}:
            raise ValueError("decision requires at and session")
        when, session = timestamp(decision["at"]), day(decision["session"])
        if (
            not start <= when <= end
            or previous is not None
            and when <= previous
            or session < result["history_start"]
            or previous_session is not None
            and session < previous_session
        ):
            raise ValueError(
                "decision clocks must increase within execution bounds and session labels cannot reverse"
            )
        decision.update(at=timestamp_text(when), session=session)
        previous, previous_session = when, session
    liquidity = result["liquidity"]
    if not isinstance(liquidity, list) or not 1 <= len(liquidity) <= 10000:
        raise ValueError(
            "strategy requires 1–10,000 explicit pre-open liquidity declarations"
        )
    seen = set()
    with arithmetic():
        for item in liquidity:
            if not isinstance(item, dict) or set(item) != {
                "instrument",
                "session",
                "quantity",
                "known_at",
            }:
                raise ValueError(
                    "liquidity requires instrument, session, quantity and known_at"
                )
            account.instrument(item["instrument"])
            item["session"] = day(item["session"])
            key = item["instrument"], item["session"]
            if key in seen:
                raise ValueError("duplicate instrument/session liquidity")
            seen.add(key)
            item["known_at"] = timestamp_text(timestamp(item["known_at"]))
            item["quantity"] = text(
                decimal_value(item["quantity"], "liquidity", nonnegative=True)
            )
    result["liquidity"] = sorted(
        liquidity, key=lambda row: (row["session"], row["instrument"])
    )
    return result


