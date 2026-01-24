"""Explicit-clock settlement batches with durable input-bound response receipts."""

import json

from .instruments import identity, timestamp, timestamp_text
from .ledger import Ledger, canonical, digest, normalize_event


class SettlementService:
    def __init__(self, path):
        self.ledger = Ledger(path)
        with self.ledger._transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS settlement_requests(request_key TEXT PRIMARY KEY,input_sha TEXT NOT NULL,response TEXT NOT NULL,response_sha TEXT NOT NULL)"
            )

