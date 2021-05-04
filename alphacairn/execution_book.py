"""Deterministic long-only order book over explicit open and close phases."""

from decimal import Decimal

from .execution_money import affordable_quantity, execution_price, fill_cost, lots
from .money import ZERO, arithmetic, decimal_value, text

LIVE = frozenset({"open", "partially_filled"})


class ExecutionBook:
    pass
