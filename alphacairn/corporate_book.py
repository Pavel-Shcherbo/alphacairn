"""Corporate action application shared by execution and strategy planning passes."""

import hashlib
from decimal import Decimal

from .execution_book import LIVE
from .money import ZERO, aligned, arithmetic, decimal_value, rounded, text


def event_id(action, kind):
    return "ca-" + kind + "-" + hashlib.sha256(action["id"].encode()).hexdigest()[:40]


