"""Exact fixed-grid return arithmetic and isolated decimal presentation."""

from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction

RETURN_PLACES = 12
OUTPUT_PLACES = 18


def fraction(value):
    return value if isinstance(value, Fraction) else Fraction(value)


def rounded_fraction(value, places):
    value = fraction(value)
    scale = 10**places
    sign = -1 if value < 0 else 1
    quotient, remainder = divmod(abs(value.numerator) * scale, value.denominator)
    if (
        2 * remainder > value.denominator
        or 2 * remainder == value.denominator
        and quotient % 2
    ):
        quotient += 1
    return Fraction(sign * quotient, scale)


