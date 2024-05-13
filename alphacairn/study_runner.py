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


def run_trial(registry, project, trial, *, actor, reason):
    with registry.transaction() as db:
        row = registry.trial(db, project, trial)
        registry.verify_trial(db, row)
        study = registry.study(db, project, row["study_id"])
        if row["status"] == "running":
            raise ValueError("trial is already owned by a running worker")
        registry.access(
            db,
            row,
            "run_result_retry" if row["status"] in TERMINAL else "run",
            actor,
            reason,
        )
        family = decode(study["definition"])["family"]
        if row["status"] in TERMINAL:
            report = decode(row["result"]) if row["result"] else None
            return {
                "record": trial_meta(row),
                "summary": summary(family, report),
                "result": report,
                "error": decode(row["error"]) if row["error"] else None,
            }
        token = uuid.uuid4().hex
        db.execute(
            "UPDATE trials SET status='running',generation=generation+1,token=?,lease_until=? WHERE id=?",
            (token, registry.now() + 600, trial),
        )
        registry.event(
            db,
            row["study_id"],
            "trial_started",
            {"trial": trial, "generation": row["generation"] + 1},
        )
        inputs = decode(row["inputs"])
        contract = decode(row["contract"])
    if (
        digest({k: v for k, v in inputs.items() if k != "sha256"}) != inputs["sha256"]
        or inputs["sha256"] != row["input_sha256"]
        or trial_contract(family, inputs) != contract
    ):
        outcome, report, error = (
            "failed",
            None,
            {
                "type": "ValueError",
                "message": "registered trial input or contract identity changed",
            },
        )
    else:
        outcome, report, error = compute(family, inputs)
    if report is not None and len(canonical(report)) > 32 * 1024 * 1024:
        outcome, report, error = (
            "failed",
            None,
            {"type": "ValueError", "message": "trial result exceeds 32 MiB"},
        )
    with registry.transaction() as db:
        current = registry.trial(db, project, trial)
        if (
            current["status"] != "running"
            or current["token"] != token
            or current["lease_until"] <= registry.now()
        ):
            raise ValueError("trial completion lost its ownership lease")
        registry.event(
            db,
            current["study_id"],
            "trial_finished",
            {
                "trial": trial,
                "status": outcome,
                "result_sha256": digest(report) if report else None,
                "error": error,
            },
        )
        db.execute(
            "UPDATE trials SET status=?,generation=generation+1,token=NULL,lease_until=NULL,result=?,error=?,finished=? WHERE id=?",
            (
                outcome,
                canonical(report) if report else None,
                canonical(error) if error else None,
                registry.now(),
                trial,
            ),
        )
        # A clock can cross the lease boundary while serializing a large result.
        if current["lease_until"] <= registry.now():
            raise ValueError("trial lease expired before completion commit")
        return {
            "record": trial_meta(registry.trial(db, project, trial)),
            "summary": summary(family, report),
            "result": report,
            "error": error,
        }
