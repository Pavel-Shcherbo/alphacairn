"""Transactional, append-only local portfolio journal with FIFO position lots."""

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .instruments import AccountSpec, identity, timestamp, timestamp_text
from .money import arithmetic, ZERO, aligned, decimal_value, exact_amount, rounded, text

SCHEMA_VERSION = 1
MAX_BATCH = 10000


def canonical(value):
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(
            "journal data must contain bounded finite JSON values"
        ) from error
    if len(payload.encode()) > 2 * 1024 * 1024:
        raise ValueError("journal object exceeds 2 MiB")
    return payload


def digest(payload):
    return hashlib.sha256(payload.encode()).hexdigest()


def normalize_event(event, spec):
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    name = identity(event.get("id"), "event ID")
    when = timestamp(event.get("timestamp"))
    kind = event.get("kind")
    signatures = {
        "deposit": {"currency", "amount"},
        "withdraw": {"currency", "amount"},
        "trade": {"instrument", "side", "quantity", "price", "fee"},
        "split": {"instrument", "numerator", "denominator"},
        "dividend": {"instrument", "gross", "withholding"},
        "fx": {"from_currency", "to_currency", "amount", "rate", "fee"},
    }
    if (
        not isinstance(kind, str)
        or kind not in signatures
        or set(event) - ({"id", "timestamp", "kind"} | signatures[kind])
    ):
        raise ValueError("event contains an unsupported kind or field")
    result = {"id": name, "timestamp": timestamp_text(when), "kind": kind}
    with arithmetic():
        if kind in ("deposit", "withdraw"):
            currency = event.get("currency")
            places = spec.places(currency)
            result.update(
                currency=currency,
                amount=text(exact_amount(event.get("amount"), places, positive=True)),
            )
        elif kind in ("trade", "split", "dividend"):
            instrument = spec.instrument(event.get("instrument"))
            places = spec.places(instrument.quote_currency)
            result["instrument"] = instrument.id
            if kind != "dividend":
                instrument.require_active(when)
            if kind == "trade":
                side = event.get("side")
                if side not in ("buy", "sell"):
                    raise ValueError("trade side must be buy or sell")
                quantity = aligned(
                    event.get("quantity"), instrument.quantity_step, "quantity"
                )
                price = aligned(event.get("price"), instrument.price_tick, "price")
                fee = exact_amount(
                    event.get("fee", "0"), places, "fee", nonnegative=True
                )
                result.update(
                    side=side,
                    quantity=text(quantity.normalize()),
                    price=text(price.normalize()),
                    fee=text(fee),
                )
            elif kind == "split":
                numerator, denominator = event.get("numerator"), event.get(
                    "denominator"
                )
                if (
                    any(
                        type(value) is not int or not 1 <= value <= 1000000
                        for value in (numerator, denominator)
                    )
                    or numerator == denominator
                ):
                    raise ValueError(
                        "split requires distinct positive integer ratio terms up to one million"
                    )
                result.update(numerator=numerator, denominator=denominator)
            else:
                gross = exact_amount(
                    event.get("gross"), places, "gross dividend", positive=True
                )
                withholding = exact_amount(
                    event.get("withholding", "0"),
                    places,
                    "withholding",
                    nonnegative=True,
                )
                if withholding > gross:
                    raise ValueError("dividend withholding exceeds gross income")
                result.update(gross=text(gross), withholding=text(withholding))
        else:
            origin, target = event.get("from_currency"), event.get("to_currency")
            if origin == target:
                raise ValueError("FX currencies must differ")
            origin_places, target_places = spec.places(origin), spec.places(target)
            amount = exact_amount(event.get("amount"), origin_places, positive=True)
            fee = exact_amount(
                event.get("fee", "0"), origin_places, "fee", nonnegative=True
            )
            rate = decimal_value(event.get("rate"), "FX rate", positive=True)
            if rounded(amount * rate, target_places) <= 0:
                raise ValueError("FX proceeds round to zero")
            result.update(
                from_currency=origin,
                to_currency=target,
                amount=text(amount),
                fee=text(fee),
                rate=text(rate.normalize()),
            )
    canonical(result)
    return result


class Ledger:
    def __init__(self, path, specification=None):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        supplied = (
            AccountSpec.compile(specification) if specification is not None else None
        )
        with self._transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS account (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, specification TEXT NOT NULL)"
            )
            row = db.execute(
                "SELECT version,specification FROM account WHERE singleton=1"
            ).fetchone()
            if row is None:
                if supplied is None:
                    raise ValueError("a new ledger requires an account specification")
                db.execute(
                    "INSERT INTO account VALUES (1,?,?)",
                    (SCHEMA_VERSION, canonical(supplied.definition())),
                )
                self.spec = supplied
            else:
                if row["version"] != SCHEMA_VERSION:
                    raise ValueError("unsupported ledger schema version")
                self.spec = AccountSpec.compile(json.loads(row["specification"]))
                if (
                    supplied is not None
                    and supplied.definition() != self.spec.definition()
                ):
                    raise ValueError(
                        "ledger belongs to a different immutable account specification"
                    )
            statements = [
                "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,timestamp TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,payload_sha256 TEXT NOT NULL,receipt TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS cash (currency TEXT PRIMARY KEY,balance TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS lots (id INTEGER PRIMARY KEY AUTOINCREMENT,event_seq INTEGER UNIQUE NOT NULL REFERENCES events(seq),instrument TEXT NOT NULL,quantity TEXT NOT NULL,basis TEXT NOT NULL,acquired_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS postings (id INTEGER PRIMARY KEY AUTOINCREMENT,event_seq INTEGER NOT NULL REFERENCES events(seq),currency TEXT NOT NULL,account TEXT NOT NULL,amount TEXT NOT NULL)",
                "CREATE INDEX IF NOT EXISTS lots_instrument ON lots(instrument,id)",
                "CREATE INDEX IF NOT EXISTS postings_event ON postings(event_seq,id)",
            ]
            for statement in statements:
                db.execute(statement)
        if new_file:
            os.chmod(self.path, 0o600)

    @contextmanager
    def _transaction(self, write=True):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            with arithmetic():
                yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _cash(self, db, currency):
        row = db.execute(
            "SELECT balance FROM cash WHERE currency=?", (currency,)
        ).fetchone()
        return Decimal(row["balance"]) if row else ZERO

    def _change_cash(self, db, currency, delta):
        balance = exact_amount(
            self._cash(db, currency) + delta, self.spec.places(currency)
        )
        if balance < 0:
            raise ValueError("insufficient settled cash")
        db.execute(
            "INSERT INTO cash VALUES (?,?) ON CONFLICT(currency) DO UPDATE SET balance=excluded.balance",
            (currency, text(balance)),
        )

