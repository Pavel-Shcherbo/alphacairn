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


