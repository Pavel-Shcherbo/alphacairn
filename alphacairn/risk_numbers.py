"""Exact fixed-grid return arithmetic and isolated decimal presentation."""

from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction

RETURN_PLACES = 12
OUTPUT_PLACES = 18


def fraction(value):
    return value if isinstance(value, Fraction) else Fraction(value)


