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


