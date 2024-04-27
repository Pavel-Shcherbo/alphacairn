"""Complete attempt/access metadata and portable replay of a selected trial."""

import json
from pathlib import Path

from .market_model import canonical, digest
from .study_model import declaration, trial_contract, require_window
from .study_runner import compute, summary
from .study_store import decode, trial_meta

MAX_EXPORT = 72 * 1024 * 1024


def events(registry, project, study):
    with registry.transaction(False) as db:
        registry.study(db, project, study)
        rows = db.execute(
            "SELECT * FROM study_events WHERE study_id=? ORDER BY sequence LIMIT 20001",
            (study,),
        ).fetchall()
    if len(rows) > 20000:
        raise ValueError("complete study audit exceeds 20,000 events")
    return [{**dict(row), "payload": decode(row["payload"])} for row in rows]


def check_chain(study, items):
    previous = digest([])
    sequence = 0
    for event in items:
        if (
            event["study_id"] != study
            or event["sequence"] <= sequence
            or event["previous_sha256"] != previous
        ):
            raise ValueError("study event order or chain parent changed")
        content = {
            "study": study,
            "kind": event["kind"],
            "payload": event["payload"],
            "previous_sha256": previous,
            "created": event["created"],
        }
        if digest(content) != event["sha256"]:
            raise ValueError("study event identity changed")
        sequence = event["sequence"]
        previous = event["sha256"]
    return previous


def validate_context(context, items):
    if (
        not isinstance(items, list)
        or not 1 <= len(items) <= 20000
        or not isinstance(context.get("trials"), list)
        or len(context["trials"]) > 100
    ):
        raise ValueError("study context exceeds complete event/attempt bounds")
    plan = declaration(context["definition"])
    head = check_chain(context["id"], items)
    if (
        not items
        or items[0]["kind"] != "study_created"
        or items[0]["payload"] != {"definition_sha256": digest(plan)}
    ):
        raise ValueError("study creation is not bound to its declaration")
    registered = {}
    states = {}
    selection = None
    access_count = 0
    contracts = {}
    finished = {}
    for event in items[1:]:
        payload = event["payload"]
        kind = event["kind"]
        trial = payload.get("trial")
        if kind == "trial_registered":
            if trial in registered:
                raise ValueError("trial registered twice in study history")
            contract = payload["contract"]
            partition = payload["partition"]
            require_window(plan, partition, contract)
            if partition == "development" and selection is not None:
                raise ValueError("development trial registered after selection")
            if partition == "holdout" and (
                selection is None
                or contract["recipe_sha256"] != selection["recipe_sha256"]
            ):
                raise ValueError("holdout registration bypassed the locked recipe")
            registered[trial] = payload
            states[trial] = "registered"
            contracts[trial] = contract
        elif kind == "trial_started":
            if states.get(trial) != "registered":
                raise ValueError("trial execution start is out of order")
            states[trial] = "running"
        elif kind == "trial_finished":
            if states.get(trial) != "running" or payload["status"] not in (
                "succeeded",
                "incomplete",
                "failed",
            ):
                raise ValueError("trial completion is out of order")
            states[trial] = payload["status"]
            finished[trial] = payload
        elif kind == "trial_interrupted":
            if states.get(trial) != "running":
                raise ValueError("trial interruption is out of order")
            states[trial] = "interrupted"
        elif kind == "selection_locked":
            if (
                selection is not None
                or states.get(trial) != "succeeded"
                or registered[trial]["partition"] != "development"
            ):
                raise ValueError("invalid study selection history")
            if any(
                states[t] in ("registered", "running")
                for t in registered
                if registered[t]["partition"] == "development"
            ):
                raise ValueError("study selected with unresolved development attempts")
            if payload["recipe_sha256"] != contracts[trial]["recipe_sha256"]:
                raise ValueError("selected recipe identity mismatch")
            selection = payload
        elif kind == "holdout_access":
            if (
                trial not in registered
                or registered[trial]["partition"] != "holdout"
                or selection is None
            ):
                raise ValueError(
                    "holdout access is not tied to a declared locked study"
                )
            if payload["purpose"] not in (
                "inspect",
                "export",
                "run",
                "run_result_retry",
                "compare",
            ):
                raise ValueError("unknown holdout access purpose")
            access_count += 1
        else:
            raise ValueError("unknown study event")
    trials = context["trials"]
    if {t["id"] for t in trials} != set(registered) or len(trials) != len(registered):
        raise ValueError("study listing omitted or duplicated registered attempts")
    for trial in trials:
        if (
            trial["status"] != states[trial["id"]]
            or trial["input_sha256"] != registered[trial["id"]]["input_sha256"]
            or trial["partition"] != registered[trial["id"]]["partition"]
        ):
            raise ValueError("trial metadata differs from the complete event history")
    if (
        context["selection"] != selection
        or context["holdout_access_attempts"] != access_count
        or context["holdout_registry_unopened"] != (access_count == 0)
        or context["registered_trial_count"] != len(trials)
        or context["failed_trial_count"]
        != sum(t["status"] in ("failed", "incomplete", "interrupted") for t in trials)
    ):
        raise ValueError("study selection/access/attempt totals differ from history")
    return {
        "passed": True,
        "complete": True,
        "study": context["id"],
        "event_head": head,
        "registered_trials": len(trials),
        "holdout_access_attempts": access_count,
        "finished": finished,
        "contracts": contracts,
    }


