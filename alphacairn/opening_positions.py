"""Explicit opening lots and marks, independent of simulated purchases."""

from decimal import Decimal

from .instruments import identity, timestamp, timestamp_text
from .money import ZERO, aligned, arithmetic, exact_amount, text

MAX_OPENING_LOTS = 1000


def normalize_opening_lot(value, account, at):
    if not isinstance(value, dict) or set(value) != {
        "id",
        "instrument",
        "quantity",
        "basis",
        "acquired_at",
    }:
        raise ValueError(
            "opening lot requires id, instrument, quantity, basis and acquired_at"
        )
    name = identity(value["id"], "opening lot ID")
    instrument = account.instrument(value["instrument"])
    acquired, opened = timestamp(value["acquired_at"]), timestamp(at)
    if acquired > opened:
        raise ValueError("opening acquisition cannot follow the opening clock")
    instrument.require_active(acquired)
    instrument.require_active(opened)
    with arithmetic():
        quantity = aligned(
            value["quantity"], instrument.quantity_step, "opening quantity"
        )
        basis = exact_amount(
            value["basis"],
            account.places(instrument.quote_currency),
            "opening basis",
            nonnegative=True,
        )
    return {
        "id": name,
        "instrument": instrument.id,
        "quantity": text(quantity),
        "basis": text(basis),
        "acquired_at": timestamp_text(acquired),
    }


