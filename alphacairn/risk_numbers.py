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


def fixed(value, places=OUTPUT_PLACES):
    value = rounded_fraction(value, places)
    scale = 10**places
    integer = value.numerator * scale // value.denominator
    sign = "-" if integer < 0 else ""
    integer = abs(integer)
    if not places:
        return sign + str(integer)
    return sign + str(integer // scale) + "." + str(integer % scale).zfill(places)


def exact(value):
    value = fraction(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


