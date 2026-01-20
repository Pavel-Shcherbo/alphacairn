"""Explicit-clock settlement batches with durable input-bound response receipts."""

import json

from .instruments import identity, timestamp, timestamp_text
from .ledger import Ledger, canonical, digest, normalize_event


class SettlementService:
    pass
