"""Reserved cash and delayed sale proceeds shared by planning and execution passes."""

from decimal import Decimal

from .instruments import timestamp
from .money import arithmetic, text
from .settlement_clock import SettlementClock


class SettlementBook:
    def __init__(self, book):
        self.book = book
        self.enabled = book.definition["version"] == 5
        self.clock = (
            SettlementClock(book.definition["settlement"], book.account)
            if self.enabled
            else None
        )
        self.settled_cash = dict(book.cash)
        self.entries = {}

    def append(self, event):
        if len(self.book.ledger_events) >= 10000:
            raise ValueError("settlement exceeds 10,000 journal events")
        self.book.ledger_events.append(event)

    def fill(
        self, fill_id, instrument, side, quantity, price, notional, fee, at, session
    ):
        due = self.clock.due(instrument.id, at, session)
        currency = instrument.quote_currency
        net = notional - fee if side == "sell" else -(notional + fee)
        if net < 0:
            self.book.cash[currency] += net
            if self.book.cash[currency] < 0:
                raise RuntimeError("settlement attempted to reserve unavailable cash")
        self.entries[fill_id] = {
            "trade_id": fill_id,
            "instrument": instrument.id,
            "side": side,
            "currency": currency,
            "kind": "receivable" if net >= 0 else "payable",
            "amount": text(abs(net)),
            "status": "pending",
            "settled_at": None,
            **due,
        }
        self.append(
            {
                "id": fill_id,
                "timestamp": at,
                "kind": "trade_pending",
                "instrument": instrument.id,
                "side": side,
                "quantity": text(quantity),
                "price": text(price),
                "fee": text(fee),
                "settles_at": due["settles_at"],
            }
        )
        if due["settles_at"] == at:
            self.settle(fill_id, at)
        return due

    def settle(self, trade_id, at):
        entry = self.entries[trade_id]
        if entry["status"] != "pending" or timestamp(at) < timestamp(
            entry["settles_at"]
        ):
            raise RuntimeError("invalid execution settlement transition")
        currency = entry["currency"]
        amount = Decimal(entry["amount"])
        if entry["kind"] == "receivable":
            self.settled_cash[currency] += amount
            self.book.cash[currency] += amount
        else:
            self.settled_cash[currency] -= amount
            if self.settled_cash[currency] < 0:
                raise RuntimeError("settlement cash became negative")
        self.append(
            {
                "id": "settle-" + trade_id,
                "timestamp": at,
                "kind": "trade_settlement",
                "trade_id": trade_id,
            }
        )
        entry.update(status="settled", settled_at=at)
        self.book.emit(
            "trade_settlement",
            at,
            trade_id=trade_id,
            currency=currency,
            amount=entry["amount"],
            direction=entry["kind"],
        )

    def process(self, at):
        if not self.enabled:
            return False
        count = 0
        with arithmetic():
            for entry in sorted(
                self.entries.values(),
                key=lambda item: (item["settles_at"], item["trade_id"]),
            ):
                if entry["status"] == "pending" and entry["settles_at"] <= at:
                    self.settle(entry["trade_id"], at)
                    count += 1
        return bool(count)

    def external_credit(self, currency, amount):
        if self.enabled:
            self.settled_cash[currency] += amount

    def outstanding(self):
        return {
            key: {
                "currency": row["currency"],
                "kind": row["kind"],
                "amount": row["amount"],
            }
            for key, row in self.entries.items()
            if row["status"] == "pending" and Decimal(row["amount"])
        }

    def summary(self):
        with arithmetic():
            return {
                "cash": [
                    {
                        "currency": currency,
                        "settled": text(value),
                        "reserved": text(value - self.book.cash[currency]),
                        "available": text(self.book.cash[currency]),
                    }
                    for currency, value in sorted(self.settled_cash.items())
                ],
                "entries": [dict(row) for row in self.entries.values()],
                "outstanding": self.outstanding(),
                "policy": "Positions change on trade date; outgoing cash is reserved immediately, incoming proceeds become spendable only on settlement. No borrowing, netting or securities-delivery restriction is inferred.",
            }
