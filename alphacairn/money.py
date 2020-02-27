"""Bounded exact decimal values and explicit currency rounding policies."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext, Context

ZERO = Decimal(0)


def arithmetic():
    return localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN))


def decimal_value(value, label="value", *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{label} requires decimal text or an integer, never float")
    if isinstance(value, str) and len(value) > 128:
        raise ValueError(f"{label} decimal text exceeds 128 characters")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} is not a decimal") from error
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    _, digits, exponent = result.as_tuple()
    if len(digits) > 38 or abs(exponent) > 18 or result.adjusted() > 37:
        raise ValueError(f"{label} exceeds the supported decimal precision")
    if positive and result <= 0 or nonnegative and result < 0:
        raise ValueError(f"{label} has an invalid sign")
    return result


def quantum(places):
    if type(places) is not int or not 0 <= places <= 18:
        raise ValueError("currency places must be between 0 and 18")
    return Decimal((0, (1,), -places))


def rounded(value, places):
    with arithmetic():
        try:
            return decimal_value(
                value.quantize(quantum(places), rounding=ROUND_HALF_EVEN)
            )
        except InvalidOperation as error:
            raise ValueError(
                "rounded amount exceeds the supported precision"
            ) from error


def exact_amount(value, places, label="amount", *, positive=False, nonnegative=False):
    result = decimal_value(value, label, positive=positive, nonnegative=nonnegative)
    with arithmetic():
        if result != result.quantize(quantum(places), rounding=ROUND_HALF_EVEN):
            raise ValueError(f"{label} contains unsupported fractional currency units")
        return decimal_value(result.quantize(quantum(places)))


