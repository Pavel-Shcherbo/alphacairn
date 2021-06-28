"""Exact fill cost, quantity affordability and last-known multi-currency marks."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .instruments import timestamp
from .money import ZERO, arithmetic, decimal_value, rounded, text


def lots(quantity, step):
    return int((quantity / step).to_integral_value(rounding=ROUND_FLOOR))


def execution_price(instrument, opening, side, slippage_bps, limit=None):
    with arithmetic():
        raw = (
            opening * (1 + slippage_bps / 10000)
            if side == "buy"
            else opening * (1 - slippage_bps / 10000)
        )
        rounding = ROUND_CEILING if side == "buy" else ROUND_FLOOR
        price = (raw / instrument.price_tick).to_integral_value(
            rounding=rounding
        ) * instrument.price_tick
        if limit is not None:
            price = min(price, limit) if side == "buy" else max(price, limit)
        return decimal_value(price, "execution price", nonnegative=True)


