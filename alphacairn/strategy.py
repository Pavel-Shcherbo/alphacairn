"""Capture, simulate and replay catalog-backed target-inventory studies."""

import argparse
import json
import sqlite3
from pathlib import Path

from .execution_export import parse_data
from .market_model import MAX_BYTES
from .market_store import MarketCatalog
from .strategy_bundle import (
    verify_strategy_bundle,
    write_strategy,
    write_strategy_inputs,
)
from .strategy_engine import simulate_strategy
from .strategy_inputs import capture_strategy


