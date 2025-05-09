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


def compile_opening(lots, marks, account, at):
    if not isinstance(lots, list) or len(lots) > MAX_OPENING_LOTS:
        raise ValueError("opening holdings support at most 1,000 lots")
    normalized = [normalize_opening_lot(item, account, at) for item in lots]
    if any(len(item["id"]) > 80 for item in normalized):
        raise ValueError("execution opening lot ID exceeds 80 characters")
    if len({item["id"] for item in normalized}) != len(normalized):
        raise ValueError("opening lot IDs must be unique")
    normalized.sort(
        key=lambda item: (item["instrument"], item["acquired_at"], item["id"])
    )
    names = {item["instrument"] for item in normalized}
    if not isinstance(marks, list) or len(marks) > len(account.instruments):
        raise ValueError("opening marks support at most one per account instrument")
    seen = set()
    quotes = []
    with arithmetic():
        for item in marks:
            if not isinstance(item, dict) or set(item) != {"instrument", "at", "price"}:
                raise ValueError("opening mark requires instrument, at and price")
            instrument = account.instrument(item["instrument"])
            if instrument.id not in names or instrument.id in seen:
                raise ValueError("opening marks require distinct held instruments")
            when = timestamp(item["at"])
            if when > timestamp(at):
                raise ValueError("opening mark cannot come from the future")
            instrument.require_active(when)
            price = aligned(item["price"], instrument.price_tick, "opening mark")
            seen.add(instrument.id)
            quotes.append(
                {
                    "instrument": instrument.id,
                    "at": timestamp_text(when),
                    "price": text(price),
                }
            )
    return normalized, sorted(quotes, key=lambda item: item["instrument"])


def opening_events(definition):
    return [
        {
            **{key: value for key, value in lot.items() if key != "id"},
            "id": "simopen-" + lot["id"],
            "kind": "opening_lot",
            "timestamp": definition["starts_at"],
        }
        for lot in definition.get("initial_lots", [])
    ]


def seed_opening(book):
    with arithmetic():
        for lot in book.definition.get("initial_lots", []):
            name = lot["instrument"]
            book.positions[name] = book.positions.get(name, ZERO) + Decimal(
                lot["quantity"]
            )
    book.ledger_events.extend(opening_events(book.definition))


def opening_marks(definition):
    return {
        item["instrument"]: {"at": item["at"], "price": item["price"]}
        for item in definition.get("initial_marks", [])
    }


def describe_opening(definition, account):
    with arithmetic():
        positions = {}
        basis = {currency: ZERO for currency, _ in account.currencies}
        for lot in definition["initial_lots"]:
            instrument = account.instrument(lot["instrument"])
            item = positions.setdefault(
                instrument.id, {"quantity": ZERO, "basis": ZERO}
            )
            item["quantity"] += Decimal(lot["quantity"])
            item["basis"] += Decimal(lot["basis"])
            basis[instrument.quote_currency] += Decimal(lot["basis"])
        return {
            "lot_count": len(definition["initial_lots"]),
            "positions": {
                name: {key: text(value) for key, value in row.items()}
                for name, row in sorted(positions.items())
            },
            "basis_by_currency": {key: text(value) for key, value in basis.items()},
            "policy": "Opening inventory is contributed at declared book basis, without cash expenditure, fees or simulated turnover; acquisition times determine FIFO before subsequent simulated purchases.",
            "basis_is_market_value": False,
            "source_authenticated": False,
        }
