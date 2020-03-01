"""Local portfolio operator CLI: journal, value, reconcile and independently audit."""

import argparse
import json
import math
import sqlite3
from pathlib import Path

from .ledger import Ledger
from .valuation import value_portfolio


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("portfolio input exceeds 2 MiB")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject(_):
        raise ValueError("portfolio input must contain finite JSON values")

    try:
        result = json.loads(
            raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=reject
        )
        pending = [(result, 0)]
        nodes = 0
        while pending:
            value, depth = pending.pop()
            nodes += 1
            if depth > 50 or nodes > 100000:
                raise ValueError("portfolio JSON exceeds depth or structure budget")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("portfolio input must contain finite values")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        return result
    except RecursionError as error:
        raise ValueError("portfolio input nesting exceeds the parser limit") from error


