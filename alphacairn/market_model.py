"""Canonical market observations with explicit event and publication clocks."""

import hashlib
import json
import re
from datetime import date, datetime, timezone

from .money import decimal_value, text

MAX_ROWS = 100_000
MAX_BYTES = 16 * 1024 * 1024


