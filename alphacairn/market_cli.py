"""Operate explicit-source market catalogs without network access."""

import argparse
import json
import sqlite3
from pathlib import Path

from .market_model import MAX_BYTES, decode, verify_snapshot
from .market_research import decision_windows, read_snapshot, write_snapshot
from .market_store import MarketCatalog


