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


def fill_cost(quantity, price, places, rate_bps, minimum):
    notional = rounded(quantity * price, places)
    fee = (
        max(rounded(notional * rate_bps / 10000, places), minimum) if quantity else ZERO
    )
    return notional, fee


def affordable_quantity(
    instrument, maximum, price, side, cash, position, places, rate_bps, minimum
):
    with arithmetic():
        count = lots(maximum, instrument.quantity_step)
        if side == "sell":
            count = min(count, lots(position, instrument.quantity_step))
            quantity = count * instrument.quantity_step
            notional, fee = fill_cost(quantity, price, places, rate_bps, minimum)
            return quantity if notional > 0 and cash + notional >= fee else ZERO
        low, high = 0, count
        while low < high:
            middle = (low + high + 1) // 2
            notional, fee = fill_cost(
                middle * instrument.quantity_step, price, places, rate_bps, minimum
            )
            if notional + fee <= cash:
                low = middle
            else:
                high = middle - 1
        quantity = low * instrument.quantity_step
        notional, _ = fill_cost(quantity, price, places, rate_bps, minimum)
        return quantity if notional > 0 else ZERO


