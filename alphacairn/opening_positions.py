"""Explicit opening lots and marks, independent of simulated purchases."""

from decimal import Decimal

from .instruments import identity, timestamp, timestamp_text
from .money import ZERO, aligned, arithmetic, exact_amount, text

MAX_OPENING_LOTS = 1000


