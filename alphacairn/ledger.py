"""Transactional, append-only local portfolio journal with FIFO position lots."""

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .instruments import AccountSpec, identity, timestamp, timestamp_text
from .money import arithmetic, ZERO, aligned, decimal_value, exact_amount, rounded, text

SCHEMA_VERSION = 1
MAX_BATCH = 10000


def canonical(value):
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(
            "journal data must contain bounded finite JSON values"
        ) from error
    if len(payload.encode()) > 2 * 1024 * 1024:
        raise ValueError("journal object exceeds 2 MiB")
    return payload


