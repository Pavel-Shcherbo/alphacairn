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

