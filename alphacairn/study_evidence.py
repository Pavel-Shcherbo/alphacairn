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


def audit_study(registry, project, study):
    # Read metadata and chain from one SQLite snapshot; never compute a trial here.
    with registry.transaction(False) as db:
        row = registry.study(db, project, study)
        trial_rows = db.execute(
            "SELECT * FROM trials WHERE study_id=? ORDER BY sequence", (study,)
        ).fetchall()
        for trial in trial_rows:
            registry.verify_trial(db, trial)
        trials = [trial_meta(t) for t in trial_rows]
        rows = db.execute(
            "SELECT * FROM study_events WHERE study_id=? ORDER BY sequence LIMIT 20001",
            (study,),
        ).fetchall()
        if len(rows) > 20000:
            raise ValueError("complete study audit exceeds 20,000 events")
        items = [{**dict(item), "payload": decode(item["payload"])} for item in rows]
        accesses = sum(e["kind"] == "holdout_access" for e in items)
        context = {
            "id": study,
            "definition": decode(row["definition"]),
            "selection": decode(row["selection"]) if row["selection"] else None,
            "trials": trials,
            "registered_trial_count": len(trials),
            "failed_trial_count": sum(
                t["status"] in ("failed", "incomplete", "interrupted") for t in trials
            ),
            "holdout_access_attempts": accesses,
            "holdout_registry_unopened": accesses == 0,
            "scope": "Registry-local access accounting only",
        }
    proof = validate_context(context, items)
    return context, items, proof


def compare_trials(registry, project, study, *, actor, reason, include_holdout=False):
    from .study_model import prose

    prose(actor, "comparison actor", 100)
    prose(reason, "comparison reason")
    if type(include_holdout) is not bool:
        raise ValueError("include_holdout must be boolean")
    with registry.transaction() as db:
        plan = decode(registry.study(db, project, study)["definition"])
        rows = db.execute(
            "SELECT * FROM trials WHERE study_id=? ORDER BY sequence", (study,)
        ).fetchall()
        comparisons = []
        for row in rows:
            withheld = row["partition"] == "holdout" and not include_holdout
            report = None
            error = None
            if not withheld:
                registry.verify_trial(db, row)
                registry.access(db, row, "compare", actor, reason)
                report = decode(row["result"]) if row["result"] else None
                error = decode(row["error"]) if row["error"] else None
            comparisons.append(
                {
                    "record": trial_meta(row),
                    "withheld": withheld,
                    "summary": summary(plan["family"], report),
                    "error": error,
                }
            )
        return {
            "study": study,
            "registered_trial_count": len(rows),
            "failed_trial_count": sum(
                r["status"] in ("failed", "incomplete", "interrupted") for r in rows
            ),
            "include_holdout": include_holdout,
            "comparisons": comparisons,
            "scope": "Registration-order comparison includes every attempt; no automatic winner or predictive-validity claim",
        }


def export_trial(registry, project, trial, *, actor, reason):
    value = registry.read(project, trial, actor=actor, reason=reason, purpose="export")
    if value["record"]["status"] not in (
        "succeeded",
        "incomplete",
        "failed",
        "interrupted",
    ):
        raise ValueError("trial must be terminal before export")
    context, items, proof = audit_study(registry, project, value["record"]["study_id"])
    document = {
        "format": "alphacairn.study-evidence.v1",
        "context": context,
        "events": items,
        "trial": value,
    }
    document["sha256"] = digest(document)
    if len(canonical(document)) > MAX_EXPORT:
        raise ValueError("study export exceeds 72 MiB")
    verify_study_export(document)
    return document


def verify_study_export(document):
    if (
        not isinstance(document, dict)
        or set(document) != {"format", "context", "events", "trial", "sha256"}
        or document["format"] != "alphacairn.study-evidence.v1"
        or len(canonical(document)) > MAX_EXPORT
        or document["sha256"]
        != digest({k: v for k, v in document.items() if k != "sha256"})
    ):
        raise ValueError("study evidence format/identity mismatch")
    context = document["context"]
    proof = validate_context(context, document["events"])
    trial = document["trial"]
    record = trial["record"]
    family = context["definition"]["family"]
    metadata = next((r for r in context["trials"] if r["id"] == record["id"]), None)
    if metadata != record:
        raise ValueError(
            "exported trial metadata differs from complete attempt listing"
        )
    contract = trial_contract(family, trial["inputs"])
    if (
        contract != trial["contract"]
        or contract != proof["contracts"][record["id"]]
        or trial["inputs"]["sha256"] != record["input_sha256"]
    ):
        raise ValueError("trial inputs differ from registered method/data identities")
    if record["status"] == "interrupted":
        if trial["result"] is not None or trial["error"] is not None:
            raise ValueError("interrupted trial contains an uncommitted result")
        return {
            "passed": True,
            "complete": False,
            "execution_replayed": False,
            "trial": record["id"],
            "reason": "Interrupted attempt retained; no completed result claimed",
            "source_authenticated": False,
        }
    status, report, error = compute(family, trial["inputs"])
    if (
        status != record["status"]
        or canonical(report) != canonical(trial["result"])
        or error != trial["error"]
    ):
        raise ValueError("fresh trial computation differs from retained result")
    finished = proof["finished"].get(record["id"])
    if (
        finished is None
        or finished["result_sha256"] != (digest(report) if report else None)
        or finished["error"] != error
    ):
        raise ValueError("trial result differs from committed completion history")
    return {
        "passed": True,
        "complete": status == "succeeded",
        "execution_replayed": True,
        "trial": record["id"],
        "status": status,
        "registered_trial_count": len(context["trials"]),
        "holdout_access_attempts": context["holdout_access_attempts"],
        "holdout_registry_unopened": context["holdout_registry_unopened"],
        "summary": summary(family, report),
        "source_authenticated": False,
        "scope": "Frozen local research replay and complete registry attempt/access history; no proof of data blindness outside the registry or predictive validity",
    }
