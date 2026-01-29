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

    def settle_due(self, at, key, *, limit=100):
        identity(key, "settlement request key")
        when = timestamp_text(timestamp(at))
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("settlement batch limit must be 1–1000")
        binding = digest(canonical({"at": when, "limit": limit}))
        with self.ledger._transaction() as db:
            prior = db.execute(
                "SELECT * FROM settlement_requests WHERE request_key=?", (key,)
            ).fetchone()
            if prior:
                if prior["input_sha"] != binding:
                    raise ValueError(
                        "settlement request key identifies different inputs"
                    )
                return self.saved(db, prior)
            count, size = db.execute(
                "SELECT count(*),COALESCE(sum(length(response)),0) FROM settlement_requests"
            ).fetchone()
            if count >= 10000 or size >= 64 * 1024 * 1024:
                raise ValueError("settlement response retention quota exceeded")
            state = self.ledger._state(db)
            if state["latest_timestamp"] and state["latest_timestamp"] > when:
                raise ValueError("settlement clock precedes the latest journal event")
            pending = state.get("settlement", {}).get("pending", [])
            if len(pending) > 10000:
                raise ValueError("settlement batch scan exceeds 10,000 pending trades")
            due = sorted(
                (row for row in pending if row["settles_at"] <= when),
                key=lambda item: (item["settles_at"], item["trade_id"]),
            )
            events = []
            for row in due[:limit]:
                event = {
                    "id": "cash-settle-" + digest(key + ":" + row["trade_id"])[:60],
                    "timestamp": when,
                    "kind": "trade_settlement",
                    "trade_id": row["trade_id"],
                }
                events.append(
                    self.ledger._apply(db, normalize_event(event, self.ledger.spec))
                )
            result = {
                "at": when,
                "settled_count": len(events),
                "remaining_due_count": max(0, len(due) - limit),
                "events": events,
            }
            raw = canonical(result)
            if size + len(raw.encode()) > 64 * 1024 * 1024:
                raise ValueError("settlement response retention quota exceeded")
            db.execute(
                "INSERT INTO settlement_requests VALUES(?,?,?,?)",
                (key, binding, raw, digest(raw)),
            )
            return result
