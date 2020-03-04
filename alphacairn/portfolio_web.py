"""Bounded disposable portfolio scenarios for the local browser workbench."""

import copy
import hashlib
import json
import tempfile
from pathlib import Path

from .instruments import AccountSpec
from .ledger import Ledger, canonical, normalize_event
from .resources import examples_directory
from .valuation import value_portfolio


def portfolio_example():
    directory = examples_directory()
    return {
        key: json.loads((directory / filename).read_text())
        for key, filename in [
            ("account", "portfolio-account.json"),
            ("events", "portfolio-events.json"),
            ("quotes", "portfolio-quotes.json"),
            ("statement", "portfolio-statement.json"),
        ]
    }


def evaluate_portfolio(params):
    if set(params) - {
        "mode",
        "account",
        "events",
        "quotes",
        "statement",
        "omit_crypto_mark",
        "inject_statement_mismatch",
    }:
        raise ValueError("portfolio request contains unsupported fields")
    defaults = portfolio_example()
    specification = params.get("account", defaults["account"])
    compiled = AccountSpec.compile(specification)
    if len(compiled.instruments) > 50:
        raise ValueError("workbench portfolio supports at most 50 instruments")
    events = params.get("events", defaults["events"])
    if not isinstance(events, list) or not 1 <= len(events) <= 500:
        raise ValueError("workbench portfolio requires 1–500 events")
    normalized = [normalize_event(event, compiled) for event in events]
    quotes = copy.deepcopy(params.get("quotes", defaults["quotes"]))
    if (
        not isinstance(quotes, dict)
        or set(quotes) - {"as_of", "marks", "fx", "max_age_seconds"}
        or not {"as_of", "marks", "fx"} <= set(quotes)
    ):
        raise ValueError("portfolio quotes require as_of, marks and fx")
    statement = copy.deepcopy(params.get("statement", defaults["statement"]))
    for flag in ("omit_crypto_mark", "inject_statement_mismatch"):
        if type(params.get(flag, False)) is not bool:
            raise ValueError("scenario controls must be boolean")
    if params.get("omit_crypto_mark"):
        if not isinstance(quotes["marks"], dict):
            raise ValueError("marks must be an object")
        for instrument in compiled.instruments:
            if instrument.kind == "crypto_spot":
                quotes["marks"].pop(instrument.id, None)
    if params.get("inject_statement_mismatch"):
        statement = copy.deepcopy(defaults["statement"])
        statement["cash"]["USD"] = "7199.00"
    with tempfile.TemporaryDirectory(prefix="alphacairn-portfolio-") as temporary:
        ledger = Ledger(Path(temporary) / "scenario.sqlite", compiled.definition())
        receipts = ledger.apply_batch(normalized)
        state = ledger.state()
        valuation = value_portfolio(
            state,
            quotes["marks"],
            quotes["fx"],
            as_of=quotes["as_of"],
            max_age_seconds=quotes.get("max_age_seconds", 86400),
        )
        reconciliation = ledger.reconcile(statement)
        audit = ledger.audit()
    inputs = {
        "account": compiled.definition(),
        "events": normalized,
        "quotes": quotes,
        "statement": statement,
    }
    return {
        "mode": "portfolio",
        "input_sha256": hashlib.sha256(canonical(inputs).encode()).hexdigest(),
        "inputs": inputs,
        "receipts": receipts,
        "state": state,
        "valuation": valuation,
        "reconciliation": reconciliation,
        "audit": audit,
        "passed": valuation["complete"]
        and reconciliation["matched"]
        and audit["passed"],
        "storage_policy": "disposable browser scenario; use the portfolio CLI for a persistent journal",
    }
