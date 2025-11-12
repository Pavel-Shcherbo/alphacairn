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

