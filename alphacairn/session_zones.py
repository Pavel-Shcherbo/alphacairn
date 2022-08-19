"""Bounded, portable timezone rules with explicit gap/fold resolution."""

import base64
import datetime as dt
import hashlib
import importlib.resources
import io
from pathlib import Path
import re
import struct
import zoneinfo

MAX_ZONE_BYTES = 1024 * 1024


def zone_key(value):
    if (
        not isinstance(value, str)
        or len(value) > 128
        or not re.fullmatch(r"[A-Za-z0-9_+./-]+", value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError("timezone requires a bounded relative IANA key")
    return value


