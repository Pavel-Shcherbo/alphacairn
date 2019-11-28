"""Stable instrument identities and local account denomination contracts."""

import datetime as dt
import re
from dataclasses import dataclass

from .money import arithmetic, decimal_value, text, quantum

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
CURRENCY = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")


def identity(value, label):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a bounded stable identifier")
    return value


