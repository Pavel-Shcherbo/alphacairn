"""Trade-date cash claims, reservations and statement coverage from journal accounts."""

from decimal import Decimal
import json

from .instruments import identity, timestamp, timestamp_text
from .money import ZERO, arithmetic, exact_amount, text

RECEIVABLE = "trade_receivable:"
PAYABLE = "trade_payable:"
SETTLED = "trade_settled:"


def trade_cash(event, places):
    from .money import rounded

    with arithmetic():
        notional = rounded(Decimal(event["quantity"]) * Decimal(event["price"]), places)
        if notional <= 0:
            raise ValueError("trade notional rounds to zero")
        fee = Decimal(event["fee"])
        return -(notional + fee) if event["side"] == "buy" else notional - fee


