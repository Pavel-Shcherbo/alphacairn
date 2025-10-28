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


def obligations(state, spec):
    result = {}
    with arithmetic():
        for currency, accounts in state.get("accounts", {}).items():
            for name, value in accounts.items():
                prefix = (
                    RECEIVABLE
                    if name.startswith(RECEIVABLE)
                    else PAYABLE if name.startswith(PAYABLE) else None
                )
                if prefix is None:
                    continue
                amount = exact_amount(
                    value, spec.places(currency), "trade settlement account"
                )
                if prefix == PAYABLE:
                    amount = -amount
                if amount < 0:
                    raise ValueError("trade settlement account has the wrong sign")
                if amount:
                    key = name[len(prefix) :]
                    if key in result:
                        raise ValueError(
                            "one trade cannot have several outstanding settlement accounts"
                        )
                    result[key] = {
                        "kind": "receivable" if prefix == RECEIVABLE else "payable",
                        "currency": currency,
                        "amount": text(amount),
                    }
    return result


def cash_summary(state, spec):
    with arithmetic():
        reserved = {currency: ZERO for currency, _ in spec.currencies}
        for value in obligations(state, spec).values():
            if value["kind"] == "payable":
                reserved[value["currency"]] += Decimal(value["amount"])
        rows = []
        for currency, _ in spec.currencies:
            settled = exact_amount(
                state["cash"].get(currency, "0"),
                spec.places(currency),
                "settled cash",
                nonnegative=True,
            )
            available = settled - reserved[currency]
            if available < 0:
                raise ValueError("settlement reservations exceed settled cash")
            rows.append(
                {
                    "currency": currency,
                    "settled": text(settled),
                    "reserved": text(
                        exact_amount(reserved[currency], spec.places(currency))
                    ),
                    "available": text(available),
                }
            )
        return rows


