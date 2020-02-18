"""Bounded exact decimal values and explicit currency rounding policies."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext, Context

ZERO = Decimal(0)


def arithmetic():
    return localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN))


