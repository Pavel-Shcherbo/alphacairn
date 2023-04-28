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

    def ex(self, action, at):
        book = self.book
        instrument = book.account.instrument(action["instrument"])
        quantity = book.positions.get(instrument.id, ZERO)
        places = book.account.places(instrument.quote_currency)
        gross = rounded(quantity * Decimal(action["amount_per_share"]), places)
        withheld = rounded(gross * Decimal(action["withholding_bps"]) / 10000, places)
        accrual = event_id(action, "accrual") if gross else None
        report = {
            "id": action["id"],
            "kind": "cash_dividend",
            "instrument": instrument.id,
            "currency": instrument.quote_currency,
            "ex_at": at,
            "pay_at": action["pay_at"],
            "eligible_quantity": text(quantity),
            "gross": text(gross),
            "withholding": text(withheld),
            "net": text(gross - withheld),
            "status": "receivable" if gross else "no_cash_entitlement",
            "accrual_event_id": accrual,
            "payment_event_id": None,
        }
        self.entitlements[action["id"]] = report
        self.reports.append(report)
        if gross:
            book.ledger_events.append(
                {
                    "id": accrual,
                    "timestamp": at,
                    "kind": "dividend_accrual",
                    "instrument": instrument.id,
                    "gross": text(gross),
                    "withholding": text(withheld),
                }
            )
        book.emit(
            "dividend_entitlement",
            at,
            action_id=action["id"],
            quantity=text(quantity),
            net=report["net"],
        )

    def pay(self, action, at):
        report = self.entitlements[action["id"]]
        if report["accrual_event_id"] is not None:
            currency = report["currency"]
            net = Decimal(report["net"])
            book = self.book
            book.cash[currency] = decimal_value(
                book.cash[currency] + net, "cash after dividend", nonnegative=True
            )
            payment = event_id(action, "payment")
            book.ledger_events.append(
                {
                    "id": payment,
                    "timestamp": at,
                    "kind": "dividend_payment",
                    "accrual_id": report["accrual_event_id"],
                }
            )
            report.update(status="paid", payment_event_id=payment)
            book.emit("dividend_payment", at, action_id=action["id"], net=report["net"])

    def outstanding(self):
        return {
            item["accrual_event_id"]: {
                "currency": item["currency"],
                "amount": item["net"],
            }
            for item in self.entitlements.values()
            if item["status"] == "receivable"
        }

    def process(self, at, groups, marks=None):
        definition = self.book.definition
        with arithmetic():
            for index in groups.get("split", []):
                name = self.split(definition["corporate_actions"][index], at)
                if marks is not None:
                    marks.pop(name, None)
            for index in groups.get("dividend_ex", []):
                self.ex(definition["corporate_actions"][index], at)
                if marks is not None:
                    marks.pop(
                        definition["corporate_actions"][index]["instrument"], None
                    )
            for index in groups.get("dividend_pay", []):
                self.pay(definition["corporate_actions"][index], at)
        if len(self.book.ledger_events) > 10000:
            raise ValueError(
                "corporate actions exceed the execution journal event budget"
            )
