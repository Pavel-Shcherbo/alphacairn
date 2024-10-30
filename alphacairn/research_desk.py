"""Scoped local research operations with atomic responses and coherent saved views."""

from contextlib import contextmanager
import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile

from .ledger import Ledger
from .instruments import timestamp, timestamp_text
from .market_model import canonical, digest
from .resources import examples_directory
from .risk_inputs import capture_risk_inputs
from .study_evidence import audit_study, compare_trials, export_trial
from .study_model import identity, key, prose
from .study_runner import run_trial, summary
from .study_store import StudyRegistry, decode

MAX_REQUEST = 8 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024


class BoundRegistry(StudyRegistry):
    """Keep existing registry operations in the caller's one request transaction."""

    def __init__(self, registry, db):
        self.path, self.clock, self.db = registry.path, registry.clock, db

    @contextmanager
    def transaction(self, write=True):
        yield self.db


def fields(value, required, optional=()):
    if (
        not isinstance(value, dict)
        or not set(required) <= set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise ValueError("research request has missing or unsupported fields")


