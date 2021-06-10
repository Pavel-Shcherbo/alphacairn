"""Create-only deterministic execution bundles and independent scenario replay."""

import csv
import hashlib
import io
import json
import os
import shutil
from pathlib import Path

from .execution_engine import simulate_execution
from .execution_model import compile_execution
from .market_model import canonical, digest, pairs

FILE_LIMIT = 24 * 1024 * 1024
BUNDLE_LIMIT = 48 * 1024 * 1024
FILES = frozenset(
    {
        "scenario.json",
        "report.json",
        "ledger-events.json",
        "fills.csv",
        "orders.csv",
        "equity.csv",
    }
)


