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


def json_data(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def parse_data(raw, limit=FILE_LIMIT):
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise ValueError("execution JSON file exceeds its byte limit")
    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ValueError("non-finite execution JSON")
            ),
        )
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid or excessively nested execution JSON") from error


