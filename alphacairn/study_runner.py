"""Execute registered frozen inputs without discarding failed or incomplete trials."""

from fractions import Fraction
import json
import sqlite3
import uuid

from .market_model import canonical, digest
from .risk_engine import analyze_risk
from .risk_numbers import fixed
from .strategy_engine import simulate_strategy
from .study_model import trial_contract
from .study_store import TERMINAL, decode, trial_meta


def compute(family, inputs):
    try:
        report = analyze_risk(inputs) if family == "risk" else simulate_strategy(inputs)
        complete = (
            report["complete"]
            if family == "risk"
            else report["execution"]["valuation"]["complete"]
        )
        return ("succeeded" if complete else "incomplete"), report, None
    except (ValueError, ArithmeticError, RuntimeError, sqlite3.Error) as error:
        return (
            "failed",
            None,
            {"type": type(error).__name__, "message": str(error)[:2048]},
        )


def summary(family, report):
    if report is None:
        return None
    if family == "risk":
        pnls = [Fraction(row["pnl"]) for row in report["stresses"] if row["complete"]]
        return {
            "equity": report["valuation"]["equity"],
            "base_currency": report["base_currency"],
            "variance_base": report["statistics"]
            .get("covariance", {})
            .get("variance_base"),
            "worst_declared_stress_pnl": fixed(min(pnls)) if pnls else None,
            "complete": report["complete"],
        }
    return {
        "equity": report["execution"]["valuation"]["equity"],
        "base_currency": report["execution"]["valuation"]["base_currency"],
        "fills": len(report["execution"]["fills"]),
        "complete": report["execution"]["valuation"]["complete"],
    }


