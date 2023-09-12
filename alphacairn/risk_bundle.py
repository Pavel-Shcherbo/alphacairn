"""Create-only risk inputs/reports and fresh offline numerical reconstruction."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from .execution_export import csv_data
from .market_model import canonical, decode, digest
from .risk_engine import analyze_risk
from .risk_inputs import prepare_risk_inputs
from .risk_model import MAX_INPUT, bounded_json

FILES = frozenset(
    {"inputs.json", "risk-report.json", "exposures.csv", "stresses.csv", "history.csv"}
)


