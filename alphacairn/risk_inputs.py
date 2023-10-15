"""Retained journal, quotes and history bound to one reproducible risk declaration."""

import copy
from dataclasses import dataclass

from .market_model import digest
from .risk_journal import capture_journal, replay_journal
from .risk_model import bounded_json, compile_history, compile_risk
from .risk_positions import validate_quotes

FORMAT = "alphacairn.risk-inputs.v1"


@dataclass(frozen=True)
class RiskInputs:
    document: dict
    spec: object
    state: dict
    configuration: dict
    history: dict
    quotes: dict
    sha256: str


def prepare_risk_inputs(value):
    bounded_json(value)
    if (
        not isinstance(value, dict)
        or set(value)
        != {"format", "journal", "quotes", "history", "configuration", "sha256"}
        or value["format"] != FORMAT
        or value["sha256"]
        != digest({key: item for key, item in value.items() if key != "sha256"})
    ):
        raise ValueError("risk inputs format or content identity mismatch")
    spec, state = replay_journal(value["journal"])
    configuration = compile_risk(value["configuration"], spec)
    history = compile_history(value["history"], spec)
    quotes = validate_quotes(value["quotes"], configuration)
    return RiskInputs(
        copy.deepcopy(value),
        spec,
        state,
        configuration,
        history,
        quotes,
        value["sha256"],
    )


def capture_risk_inputs(database, configuration, history, quotes):
    journal = capture_journal(database)
    spec, _ = replay_journal(journal)
    configuration = compile_risk(configuration, spec)
    document = {
        "format": FORMAT,
        "journal": journal,
        "quotes": validate_quotes(quotes, configuration),
        "history": compile_history(history, spec),
        "configuration": configuration,
    }
    document["sha256"] = digest(document)
    prepare_risk_inputs(document)
    return document
