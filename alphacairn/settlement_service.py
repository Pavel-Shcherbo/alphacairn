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

    @staticmethod
    def saved(db, row):
        response = json.loads(row["response"])
        if digest(canonical(response)) != row["response_sha"] or response[
            "settled_count"
        ] != len(response["events"]):
            raise ValueError("settlement response receipt identity differs")
        for event in response["events"]:
            actual = db.execute(
                "SELECT receipt FROM events WHERE event_id=? AND kind='trade_settlement'",
                (event["id"],),
            ).fetchone()
            if actual is None or json.loads(actual["receipt"]) != {
                key: value for key, value in event.items() if key != "duplicate"
            }:
                raise ValueError(
                    "settlement receipt differs from its accepted journal event"
                )
        return response

    def receipt(self, key):
        identity(key, "settlement request key")
        with self.ledger._transaction(write=False) as db:
            row = db.execute(
                "SELECT * FROM settlement_requests WHERE request_key=?", (key,)
            ).fetchone()
            if row is None:
                raise ValueError("settlement response receipt not found")
            return self.saved(db, row)

