"""Corporate action application shared by execution and strategy planning passes."""

import hashlib
from decimal import Decimal

from .execution_book import LIVE
from .money import ZERO, aligned, arithmetic, decimal_value, rounded, text


def event_id(action, kind):
    return "ca-" + kind + "-" + hashlib.sha256(action["id"].encode()).hexdigest()[:40]


def scaled(value, n, d, step, label):
    result = aligned(value * n / d, step, label) if value else ZERO
    if result * d != value * n:
        raise ValueError(label + " cannot be represented exactly")
    return result


class CorporateBook:
    def __init__(self, book):
        self.book = book
        self.entitlements = {}
        self.reports = []

    def split(self, action, at):
        book = self.book
        instrument = book.account.instrument(action["instrument"])
        name = instrument.id
        n, d = action["numerator"], action["denominator"]
        before = book.positions.get(name, ZERO)
        after = scaled(before, n, d, instrument.quantity_step, "post-split position")
        adjustments = []
        for order in sorted(book.orders.values(), key=book.priority):
            definition = order["definition"]
            if order["status"] not in LIVE or definition["instrument"] != name:
                continue
            if action["order_policy"] == "cancel":
                book.terminal(order, "cancelled", at, "corporate_split_policy")
                adjustments.append({"order_id": definition["id"], "policy": "cancel"})
                continue
            remaining = scaled(
                order["remaining"],
                n,
                d,
                instrument.quantity_step,
                "post-split order remainder",
            )
            filled = scaled(
                order["filled"],
                n,
                d,
                instrument.quantity_step,
                "post-split order filled quantity",
            )
            limit = (
                scaled(
                    Decimal(definition["limit"]),
                    d,
                    n,
                    instrument.price_tick,
                    "post-split order limit",
                )
                if definition["limit"] is not None
                else None
            )
            change = {
                "action_id": action["id"],
                "at": at,
                "numerator": n,
                "denominator": d,
                "remaining_before": text(order["remaining"]),
                "remaining_after": text(remaining),
                "filled_before": text(order["filled"]),
                "filled_after": text(filled),
                "limit_before": definition["limit"],
                "limit_after": text(limit) if limit is not None else None,
            }
            order["remaining"], order["filled"] = remaining, filled
            definition["quantity"] = text(remaining + filled)
            definition["limit"] = change["limit_after"]
            order["corporate_adjustments"].append(change)
            adjustments.append(
                {"order_id": definition["id"], "policy": "adjust", **change}
            )
        book.positions[name] = after
        journal_id = None
        if before:
            journal_id = event_id(action, "split")
            book.ledger_events.append(
                {
                    "id": journal_id,
                    "timestamp": at,
                    "kind": "split",
                    "instrument": name,
                    "numerator": n,
                    "denominator": d,
                }
            )
        report = {
            "id": action["id"],
            "kind": "split",
            "at": at,
            "instrument": name,
            "position_before": text(before),
            "position_after": text(after),
            "order_adjustments": adjustments,
            "ledger_event_id": journal_id,
        }
        self.reports.append(report)
        book.emit("corporate_split", at, action_id=action["id"], instrument=name)
        return name

