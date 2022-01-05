"""Portable strategy inputs, decision traces and independently replayed executions."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from .execution_export import (
    FILES as EXECUTION_FILES,
    csv_data,
    json_data,
    parse_data,
    verify_execution_bundle,
    write_execution,
)
from .market_model import MAX_BYTES, canonical, digest
from .strategy_engine import simulate_strategy
from .strategy_inputs import prepare_strategy_inputs

ROOT_FILES = frozenset({"inputs.json", "strategy-report.json", "decisions.csv"})
ALL_FILES = ROOT_FILES | {
    "execution/" + name for name in EXECUTION_FILES | {"manifest.json"}
}
TOTAL_LIMIT = 128 * 1024 * 1024


