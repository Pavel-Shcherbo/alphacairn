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

