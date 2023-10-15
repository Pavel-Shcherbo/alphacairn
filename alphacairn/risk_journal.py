"""Read-only coherent journal backup and independent accepted-event reconstruction."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from .instruments import AccountSpec
from .ledger import Ledger, digest as ledger_digest
from .market_model import canonical
from .risk_model import bounded_json

MAX_EVENTS = 10000
MAX_DATABASE = 32 * 1024 * 1024


