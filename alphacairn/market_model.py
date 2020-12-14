"""Canonical market observations with explicit event and publication clocks."""

import hashlib
import json
import re
from datetime import date, datetime, timezone

from .money import decimal_value, text

MAX_ROWS = 100_000
MAX_BYTES = 16 * 1024 * 1024


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}", value
    ):
        raise ValueError(
            f"{label} must be an explicit identifier of at most 96 characters"
        )
    return value


