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

