"""Frozen attempts, selection discipline, access history and independent replay."""

import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import concurrent.futures
import subprocess
import sys

from alphacairn.instruments import timestamp, timestamp_text
from alphacairn.ledger import Ledger
from alphacairn.market_model import digest, canonical
from alphacairn.market_store import MarketCatalog
from alphacairn.risk_inputs import capture_risk_inputs
from alphacairn.study_model import declaration
from alphacairn.study_store import StudyRegistry
from alphacairn.study_runner import run_trial
from alphacairn.study_evidence import (
    audit_study,
    export_trial,
    verify_study_export,
    compare_trials,
)
from alphacairn.strategy_inputs import capture_strategy

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


