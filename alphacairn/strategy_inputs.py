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
    expected_execution = EXECUTION_FIELDS
    if (
        isinstance(execution, dict)
        and type(execution.get("version")) is int
        and execution["version"] == 2
    ):
        expected_execution = EXECUTION_FIELDS | {"calendar", "calendar_policy"}
    if not isinstance(execution, dict) or set(execution) != expected_execution:
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


def realization_queries(config):
    return [
        validate_query(
            {
                "kind": "bar",
                "source": config["source"],
                "instrument": name,
                **config["execution_sessions"],
                "known_at": config["market_cutoff"],
                "clock": config["clock"],
            }
        )
        for name in config["allocation_order"]
    ]


def membership_query(config, decision):
    return validate_query(
        {
            "kind": "membership",
            "source": config["source"],
            "universe": config["universe"],
            "on": decision["session"],
            "known_at": decision["at"],
            "clock": config["clock"],
        }
    )


def feature_query(config, decision, name):
    return validate_query(
        {
            "kind": "bar",
            "source": config["source"],
            "instrument": name,
            "start": config["history_start"],
            "end": decision["session"],
            "known_at": decision["at"],
            "clock": config["clock"],
        }
    )


def capture_strategy(catalog, definition):
    config = compile_strategy(definition)
    snapshots = {}
    records, retained_bytes = 0, 0
    with catalog.read_view() as view:

        def get(query):
            nonlocal records, retained_bytes
            key = digest(query)
            if key not in snapshots:
                value = view.snapshot(query)
                records += len(value["records"])
                retained_bytes += len(canonical(value))
                if records > 100000 or retained_bytes > MAX_BYTES:
                    raise ValueError(
                        "strategy input snapshots exceed record or byte budget"
                    )
                snapshots[key] = value
            return snapshots[key]

        for query in realization_queries(config):
            get(query)
        for decision in config["decisions"]:
            members = get(membership_query(config, decision))["records"]
            if len(members) > 100:
                raise ValueError("strategy decision exceeds 100 universe members")
            for record in members:
                name = record["observation"]["instrument"]
                if name not in config["target_quantities"]:
                    raise ValueError(
                        "historical universe contains an instrument missing from the account: "
                        + name
                    )
                get(feature_query(config, decision, name))
    result = {
        "format": "alphacairn.strategy-inputs.v1",
        "configuration": config,
        "snapshots": [snapshots[key] for key in sorted(snapshots)],
    }
    result["sha256"] = digest(result)
    prepare_strategy_inputs(result)
    return result


@dataclass(frozen=True)
class StrategyInputs:
    configuration: dict
    execution: ExecutionPlan
    windows: list
    sha256: str


def prepare_strategy_inputs(document):
    if len(canonical(document)) > MAX_BYTES:
        raise ValueError("strategy inputs exceed 16 MiB")
    if (
        not isinstance(document, dict)
        or set(document) != {"format", "configuration", "snapshots", "sha256"}
        or document["format"] != "alphacairn.strategy-inputs.v1"
    ):
        raise ValueError("unsupported strategy inputs")
    if (
        digest({key: value for key, value in document.items() if key != "sha256"})
        != document["sha256"]
    ):
        raise ValueError("strategy input digest mismatch")
    config = compile_strategy(document["configuration"])
    if config != document["configuration"]:
        raise ValueError("strategy configuration is not canonical")
    items = document["snapshots"]
    if not isinstance(items, list) or not 1 <= len(items) <= 10200:
        raise ValueError("strategy inputs require a bounded snapshot list")
    snapshots, used, records = {}, set(), 0
    for item in items:
        verify_snapshot(item)
        key = digest(validate_query(item["query"]))
        if key in snapshots:
            raise ValueError("duplicate strategy snapshot query")
        snapshots[key] = item
        records += len(item["records"])
        if records > 100000:
            raise ValueError("strategy inputs exceed 100,000 retained observations")

    def get(query):
        key = digest(query)
        if key not in snapshots:
            raise ValueError("strategy inputs are missing a required market query")
        used.add(key)
        return snapshots[key]

    liquidity = {
        (row["instrument"], row["session"]): row for row in config["liquidity"]
    }
    consumed, bars = set(), []
    for query in realization_queries(config):
        for record in get(query)["records"]:
            row = record["observation"]
            opened, closed = timestamp(row["opened_at"]), timestamp(row["closed_at"])
            # Session labels are caller-declared; execution bounds use actual instants.
            if (
                not timestamp(config["execution"]["starts_at"])
                <= opened
                < closed
                <= timestamp(config["execution"]["ends_at"])
            ):
                continue
            key = row["instrument"], row["session"]
            if key not in liquidity:
                raise ValueError(
                    "missing explicit pre-open liquidity for execution bar"
                )
            supply = liquidity[key]
            consumed.add(key)
            bars.append(
                {
                    **{
                        field: row[field]
                        for field in (
                            "instrument",
                            "session",
                            "opened_at",
                            "closed_at",
                            "open",
                            "high",
                            "low",
                            "close",
                        )
                    },
                    "liquidity": supply["quantity"],
                    "liquidity_known_at": supply["known_at"],
                }
            )
    if consumed != set(liquidity):
        raise ValueError("liquidity declaration has no matching execution-vintage bar")
    plan = compile_execution({**config["execution"], "bars": bars, "commands": []})
    windows = []
    with arithmetic():
        for decision in config["decisions"]:
            member_snapshot = get(membership_query(config, decision))
            members = member_snapshot["records"]
            if len(members) > 100:
                raise ValueError("strategy decision exceeds 100 members")
            features = []
            for member in sorted(
                members, key=lambda row: row["observation"]["instrument"]
            ):
                name = member["observation"]["instrument"]
                if name not in config["target_quantities"]:
                    raise ValueError(
                        "historical universe instrument is undeclared by the account"
                    )
                snapshot = get(feature_query(config, decision, name))
                history = sorted(
                    snapshot["records"], key=lambda row: row["observation"]["session"]
                )
                if any(
                    timestamp(left["observation"]["closed_at"])
                    > timestamp(right["observation"]["opened_at"])
                    for left, right in zip(history, history[1:])
                ):
                    raise ValueError(
                        "feature history bars overlap or contradict session ordering"
                    )
                rows = history[-config["lookback"] :]
                item = {
                    "instrument": name,
                    "snapshot_sha256": snapshot["sha256"],
                    "observations": [row["observation_sha256"] for row in rows],
                    "sessions": [row["observation"]["session"] for row in rows],
                    "available": len(rows),
                    "ready": False,
                    "reason": "insufficient_history",
                    "last_close": None,
                    "mean_close": None,
                    "above_mean": None,
                    "age_seconds": None,
                }
                if rows:
                    last = rows[-1]["observation"]
                    age = (
                        timestamp(decision["at"]) - timestamp(last["closed_at"])
                    ).total_seconds()
                    item.update(last_close=last["close"], age_seconds=age)
                    if len(rows) == config["lookback"]:
                        prices = [Decimal(row["observation"]["close"]) for row in rows]
                        total = sum(prices, Decimal(0))
                        ready = age <= config["max_feature_age_seconds"]
                        item.update(
                            ready=ready,
                            reason="ready" if ready else "stale_history",
                            mean_close=text(total / Decimal(len(prices))),
                            above_mean=(
                                prices[-1] * len(prices) > total if ready else None
                            ),
                        )
                features.append(item)
            windows.append(
                {
                    "decision": copy.deepcopy(decision),
                    "membership_sha256": member_snapshot["sha256"],
                    "features": features,
                }
            )
    if used != set(snapshots):
        raise ValueError("strategy inputs contain unused market queries")
    return StrategyInputs(config, plan, windows, document["sha256"])
