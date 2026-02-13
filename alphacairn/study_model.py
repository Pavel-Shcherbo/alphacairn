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


def trial_contract(family, inputs):
    if len(canonical(inputs)) > MAX_INPUT:
        raise ValueError("trial inputs exceed 16 MiB")
    if family == "risk":
        prepared = prepare_risk_inputs(inputs)
        config = copy.deepcopy(prepared.configuration)
        start, end = config["history_start"], config["as_of"]
        for field in ("name", "as_of", "history_start", "history_end"):
            config.pop(field)
        recipe = {
            "family": family,
            "account": prepared.spec.definition(),
            "configuration": config,
        }
    elif family == "strategy":
        prepared = prepare_strategy_inputs(inputs)
        config = copy.deepcopy(prepared.configuration)
        start, end = config["execution"]["starts_at"], config["execution"]["ends_at"]
        for field in (
            "history_start",
            "decisions",
            "market_cutoff",
            "execution_sessions",
            "liquidity",
        ):
            config.pop(field)
        for field in (
            "starts_at",
            "ends_at",
            "fx",
            "corporate_actions",
            "initial_marks",
        ):
            config["execution"].pop(field, None)
        if config["execution"]["version"] == 5:
            settlement = config["execution"]["settlement"]
            calendar = settlement["calendar"]
            settlement["calendar"] = (
                None
                if calendar is None
                else {
                    "source": calendar["definition"]["source"],
                    "calendars": [
                        {
                            key: row[key]
                            for key in ("id", "timezone", "weekdays", "segments")
                        }
                        for row in calendar["definition"]["calendars"]
                    ],
                    "zones": [
                        {key: row[key] for key in ("key", "sha256")}
                        for row in calendar["zones"]
                    ],
                }
            )
        recipe = {"family": family, "configuration": config}
    else:
        raise ValueError("unknown study family")
    return {
        "inputs_sha256": inputs["sha256"],
        "recipe_sha256": digest(recipe),
        "recipe": recipe,
        "start": start,
        "end": end,
    }


def require_window(plan, partition, contract):
    if partition not in ("development", "holdout"):
        raise ValueError("trial partition must be development or holdout")
    window = plan[partition]
    if not window["start"] <= contract["start"] <= contract["end"] <= window["end"]:
        raise ValueError(
            "trial observation/exposure window lies outside its declared partition"
        )
