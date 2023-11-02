"""Bounded risk-study declarations and synchronous operator-supplied history."""

import copy
from fractions import Fraction

from .instruments import identity, timestamp, timestamp_text
from .market_model import canonical
from .money import decimal_value, text

MAX_INPUT = 16 * 1024 * 1024
MAX_FACTORS = 24
MAX_POINTS = 1001


