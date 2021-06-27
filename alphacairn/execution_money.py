"""Exact fill cost, quantity affordability and last-known multi-currency marks."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .instruments import timestamp
from .money import ZERO, arithmetic, decimal_value, rounded, text


def lots(quantity, step):
    return int((quantity / step).to_integral_value(rounding=ROUND_FLOOR))


