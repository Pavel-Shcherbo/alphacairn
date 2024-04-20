"""Declare, retain, select and audit frozen risk or strategy research attempts."""

import argparse
import json
from pathlib import Path
import sqlite3

from .execution_export import parse_data
from .market_model import canonical
from .study_store import StudyRegistry
from .study_runner import run_trial
from .study_evidence import (
    audit_study,
    export_trial,
    verify_study_export,
    MAX_EXPORT,
    compare_trials,
    events,
    check_chain,
)


def load(path, limit=16 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        return parse_data(stream.read(limit + 1), limit)


