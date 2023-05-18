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
        "dividend_accrual": {"instrument", "gross", "withholding"},
        "dividend_payment": {"accrual_id"},
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
        elif kind == "dividend_payment":
            result["accrual_id"] = identity(
                event.get("accrual_id"), "dividend accrual ID"
            )
        elif kind in ("trade", "split", "dividend", "dividend_accrual"):
            instrument = spec.instrument(event.get("instrument"))
            places = spec.places(instrument.quote_currency)
            result["instrument"] = instrument.id
            if kind in ("trade", "split"):
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
                "CREATE INDEX IF NOT EXISTS postings_account ON postings(account,currency)",
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

    def apply(self, event):
        return self.apply_batch([event])[0]

    def apply_batch(self, events):
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_BATCH:
            raise ValueError("event batch requires 1–10000 events")
        normalized = [normalize_event(event, self.spec) for event in events]
        with self._transaction() as db:
            return [self._apply(db, event) for event in normalized]

    def _apply(self, db, event):
        payload = canonical(event)
        fingerprint = digest(payload)
        existing = db.execute(
            "SELECT payload_sha256,receipt FROM events WHERE event_id=?", (event["id"],)
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != fingerprint:
                raise ValueError("event ID conflicts with a different payload")
            return {**json.loads(existing["receipt"]), "duplicate": True}
        previous = db.execute(
            "SELECT timestamp FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if previous and event["timestamp"] < previous["timestamp"]:
            raise ValueError("new events must not precede the latest journal timestamp")
        cursor = db.execute(
            "INSERT INTO events(event_id,timestamp,kind,payload,payload_sha256,receipt) VALUES (?,?,?,?,?,?)",
            (
                event["id"],
                event["timestamp"],
                event["kind"],
                payload,
                fingerprint,
                "{}",
            ),
        )
        sequence = cursor.lastrowid
        postings, matches = [], []

        def post(currency, account, amount):
            amount = exact_amount(amount, self.spec.places(currency))
            postings.append(
                {"currency": currency, "account": account, "amount": text(amount)}
            )

        kind = event["kind"]
        if kind in ("deposit", "withdraw"):
            currency = event["currency"]
            amount = Decimal(event["amount"]) * (1 if kind == "deposit" else -1)
            self._change_cash(db, currency, amount)
            post(currency, "cash", amount)
            post(currency, "external_capital", -amount)
        elif kind == "dividend_payment":
            parent = db.execute(
                "SELECT payload FROM events WHERE event_id=? AND kind='dividend_accrual'",
                (event["accrual_id"],),
            ).fetchone()
            if parent is None:
                raise ValueError("dividend payment requires an earlier accrual")
            accrual = json.loads(parent["payload"])
            marker = "dividend_settled:" + event["accrual_id"]
            if db.execute(
                "SELECT 1 FROM postings WHERE account=? LIMIT 1", (marker,)
            ).fetchone():
                raise ValueError("dividend accrual has already been paid")
            instrument = self.spec.instrument(accrual["instrument"])
            currency = instrument.quote_currency
            net = Decimal(accrual["gross"]) - Decimal(accrual["withholding"])
            self._change_cash(db, currency, net)
            post(currency, "cash", net)
            post(currency, "dividend_receivable:" + event["accrual_id"], -net)
            post(currency, marker, ZERO)
        elif kind == "fx":
            origin, target = event["from_currency"], event["to_currency"]
            amount, fee, rate = map(
                Decimal, (event["amount"], event["fee"], event["rate"])
            )
            proceeds = rounded(amount * rate, self.spec.places(target))
            self._change_cash(db, origin, -(amount + fee))
            self._change_cash(db, target, proceeds)
            post(origin, "cash", -(amount + fee))
            post(origin, "fx_clearing", amount)
            post(origin, "fx_fees", fee)
            post(target, "cash", proceeds)
            post(target, "fx_clearing", -proceeds)
        else:
            instrument = self.spec.instrument(event["instrument"])
            currency, places = instrument.quote_currency, self.spec.places(
                instrument.quote_currency
            )
            if kind in ("dividend", "dividend_accrual"):
                gross, withholding = Decimal(event["gross"]), Decimal(
                    event["withholding"]
                )
                if kind == "dividend":
                    self._change_cash(db, currency, gross - withholding)
                    post(currency, "cash", gross - withholding)
                else:
                    post(
                        currency,
                        "dividend_receivable:" + event["id"],
                        gross - withholding,
                    )
                post(currency, "dividend_income", -gross)
                post(currency, "withholding", withholding)
            elif kind == "split":
                lots = db.execute(
                    "SELECT * FROM lots WHERE instrument=? ORDER BY id",
                    (instrument.id,),
                ).fetchall()
                if not any(Decimal(lot["quantity"]) > 0 for lot in lots):
                    raise ValueError("split requires an open position")
                for lot in lots:
                    quantity = Decimal(lot["quantity"])
                    if not quantity:
                        continue
                    adjusted = quantity * event["numerator"] / event["denominator"]
                    adjusted = aligned(
                        adjusted, instrument.quantity_step, "post-split lot quantity"
                    )
                    if adjusted * event["denominator"] != quantity * event["numerator"]:
                        raise ValueError("split ratio cannot be represented exactly")
                    db.execute(
                        "UPDATE lots SET quantity=? WHERE id=?",
                        (text(adjusted), lot["id"]),
                    )
            else:
                quantity, price, fee = map(
                    Decimal, (event["quantity"], event["price"], event["fee"])
                )
                notional = rounded(quantity * price, places)
                if notional <= 0:
                    raise ValueError("trade notional rounds to zero")
                if event["side"] == "buy":
                    basis = exact_amount(notional + fee, places)
                    self._change_cash(db, currency, -basis)
                    db.execute(
                        "INSERT INTO lots(event_seq,instrument,quantity,basis,acquired_at) VALUES (?,?,?,?,?)",
                        (
                            sequence,
                            instrument.id,
                            text(quantity),
                            text(basis),
                            event["timestamp"],
                        ),
                    )
                    post(currency, "cash", -basis)
                    post(currency, "inventory:" + instrument.id, basis)
                else:
                    remaining, released_basis = quantity, ZERO
                    lots = db.execute(
                        "SELECT * FROM lots WHERE instrument=? ORDER BY id",
                        (instrument.id,),
                    ).fetchall()
                    if sum((Decimal(lot["quantity"]) for lot in lots), ZERO) < quantity:
                        raise ValueError(
                            "insufficient position; short selling is unsupported"
                        )
                    for lot in lots:
                        available, basis = Decimal(lot["quantity"]), Decimal(
                            lot["basis"]
                        )
                        if not available or not remaining:
                            continue
                        taken = min(available, remaining)
                        allocated = (
                            basis
                            if taken == available
                            else rounded(basis * taken / available, places)
                        )
                        db.execute(
                            "UPDATE lots SET quantity=?,basis=? WHERE id=?",
                            (
                                text(available - taken),
                                text(basis - allocated),
                                lot["id"],
                            ),
                        )
                        remaining -= taken
                        released_basis += allocated
                        matches.append(
                            {
                                "lot_id": lot["id"],
                                "quantity": text(taken),
                                "basis": text(allocated),
                            }
                        )
                    proceeds = exact_amount(notional - fee, places)
                    self._change_cash(db, currency, proceeds)
                    post(currency, "cash", proceeds)
                    post(currency, "inventory:" + instrument.id, -released_basis)
                    post(
                        currency,
                        "realized_income:" + instrument.id,
                        -(proceeds - released_basis),
                    )
        totals = {}
        for item in postings:
            totals[item["currency"]] = totals.get(item["currency"], ZERO) + Decimal(
                item["amount"]
            )
        if any(value != 0 for value in totals.values()):
            raise RuntimeError("internal journal balancing invariant failed")
        db.executemany(
            "INSERT INTO postings(event_seq,currency,account,amount) VALUES (?,?,?,?)",
            [
                (sequence, item["currency"], item["account"], item["amount"])
                for item in postings
            ],
        )
        receipt = {
            "sequence": sequence,
            "id": event["id"],
            "timestamp": event["timestamp"],
            "kind": kind,
            "postings": postings,
            "fifo_matches": matches,
        }
        db.execute(
            "UPDATE events SET receipt=? WHERE seq=?", (canonical(receipt), sequence)
        )
        return {**receipt, "duplicate": False}

    def _state(self, db):
        cash = {
            row["currency"]: row["balance"]
            for row in db.execute("SELECT * FROM cash ORDER BY currency")
        }
        lots = []
        positions = {}
        for row in db.execute("SELECT * FROM lots ORDER BY id"):
            quantity, basis = Decimal(row["quantity"]), Decimal(row["basis"])
            if quantity <= 0:
                continue
            lots.append(dict(row))
            position = positions.setdefault(
                row["instrument"], {"quantity": ZERO, "basis": ZERO}
            )
            position["quantity"] += quantity
            position["basis"] += basis
        positions = {
            name: {key: text(value) for key, value in values.items()}
            for name, values in sorted(positions.items())
        }
        accounts = {}
        for row in db.execute(
            "SELECT currency,account,amount FROM postings ORDER BY id"
        ):
            account = accounts.setdefault(row["currency"], {})
            account[row["account"]] = account.get(row["account"], ZERO) + Decimal(
                row["amount"]
            )
        accounts = {
            currency: {name: text(value) for name, value in sorted(values.items())}
            for currency, values in sorted(accounts.items())
        }
        last = db.execute(
            "SELECT seq,timestamp FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return {
            "account": self.spec.definition(),
            "cash": cash,
            "positions": positions,
            "lots": lots,
            "accounts": accounts,
            "last_sequence": last["seq"] if last else 0,
            "latest_timestamp": last["timestamp"] if last else None,
        }

    def state(self):
        with self._transaction(write=False) as db:
            return self._state(db)

    def events(self, after=0, limit=100):
        if (
            type(after) is not int
            or after < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ValueError(
                "event cursor must be nonnegative and limit between 1 and 1000"
            )
        with self._transaction(write=False) as db:
            rows = db.execute(
                "SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)
            ).fetchall()
            return [
                {
                    "sequence": row["seq"],
                    "event": json.loads(row["payload"]),
                    "payload_sha256": row["payload_sha256"],
                    "receipt": json.loads(row["receipt"]),
                }
                for row in rows
            ]

    def reconcile(self, observed):
        if (
            not isinstance(observed, dict)
            or set(observed) != {"cash", "positions"}
            or not all(isinstance(observed[key], dict) for key in observed)
        ):
            raise ValueError("reconciliation requires cash and positions objects")
        cash, positions = {}, {}
        with arithmetic():
            for currency, amount in observed["cash"].items():
                cash[currency] = exact_amount(
                    amount, self.spec.places(currency), nonnegative=True
                )
            for name, quantity in observed["positions"].items():
                instrument = self.spec.instrument(name)
                value = decimal_value(quantity, "observed quantity", nonnegative=True)
                if value:
                    aligned(value, instrument.quantity_step, "observed quantity")
                positions[name] = value
            state = self.state()
            differences = []
            for kind, actual, expected in [
                (
                    "cash",
                    cash,
                    {key: Decimal(value) for key, value in state["cash"].items()},
                ),
                (
                    "positions",
                    positions,
                    {
                        key: Decimal(value["quantity"])
                        for key, value in state["positions"].items()
                    },
                ),
            ]:
                for key in sorted(actual.keys() | expected.keys()):
                    wanted, found = expected.get(key, ZERO), actual.get(key, ZERO)
                    if wanted != found:
                        differences.append(
                            {
                                "kind": kind,
                                "key": key,
                                "expected": text(wanted),
                                "observed": text(found),
                                "difference": text(found - wanted),
                            }
                        )
        return {
            "matched": not differences,
            "sequence": state["last_sequence"],
            "differences": differences,
            "policy": "exact comparison; missing keys are zero; no automatic reconciliation entries",
        }

    def audit(self):
        with self._transaction(write=False) as db:
            state = self._state(db)
            issues, event_totals = [], {}
            history = db.execute(
                "SELECT seq,payload,payload_sha256,receipt FROM events ORDER BY seq"
            ).fetchall()
            for row in history:
                if digest(row["payload"]) != row["payload_sha256"]:
                    issues.append(
                        {"code": "event_hash_mismatch", "sequence": row["seq"]}
                    )
            for row in db.execute(
                "SELECT event_seq,currency,amount FROM postings ORDER BY id"
            ):
                key = (row["event_seq"], row["currency"])
                event_totals[key] = event_totals.get(key, ZERO) + Decimal(row["amount"])
            for (sequence, currency), amount in event_totals.items():
                if amount:
                    issues.append(
                        {
                            "code": "unbalanced_event",
                            "sequence": sequence,
                            "currency": currency,
                        }
                    )
            for currency in dict(self.spec.currencies):
                journal_cash = Decimal(
                    state["accounts"].get(currency, {}).get("cash", "0")
                )
                if journal_cash != Decimal(state["cash"].get(currency, "0")):
                    issues.append({"code": "cash_cache_mismatch", "currency": currency})
            for instrument in self.spec.instruments:
                journal_basis = Decimal(
                    state["accounts"]
                    .get(instrument.quote_currency, {})
                    .get("inventory:" + instrument.id, "0")
                )
                lot_basis = Decimal(
                    state["positions"].get(instrument.id, {}).get("basis", "0")
                )
                if journal_basis != lot_basis:
                    issues.append(
                        {
                            "code": "inventory_basis_mismatch",
                            "instrument": instrument.id,
                        }
                    )
            for row in db.execute("SELECT id,quantity,basis FROM lots ORDER BY id"):
                quantity, basis = Decimal(row["quantity"]), Decimal(row["basis"])
                if quantity < 0 or basis < 0 or quantity == 0 and basis != 0:
                    issues.append({"code": "invalid_lot_balance", "lot_id": row["id"]})
        # Rebuild from the accepted event stream independently of persisted lots
        # and cash caches. This also checks quantity changes such as stock splits.
        try:
            with tempfile.TemporaryDirectory(prefix="alphacairn-audit-") as temporary:
                replay = Ledger(
                    Path(temporary) / "replay.sqlite", self.spec.definition()
                )
                for offset in range(0, len(history), 1000):
                    chunk = history[offset : offset + 1000]
                    receipts = replay.apply_batch(
                        [json.loads(row["payload"]) for row in chunk]
                    )
                    for original, receipt in zip(chunk, receipts):
                        receipt.pop("duplicate")
                        if canonical(receipt) != original["receipt"]:
                            issues.append(
                                {
                                    "code": "receipt_replay_mismatch",
                                    "sequence": original["seq"],
                                }
                            )
                restored = replay.state()
                for component in (
                    "cash",
                    "positions",
                    "lots",
                    "accounts",
                    "last_sequence",
                    "latest_timestamp",
                ):
                    if restored[component] != state[component]:
                        issues.append(
                            {"code": "state_replay_mismatch", "component": component}
                        )
        except (ValueError, KeyError, sqlite3.Error):
            issues.append({"code": "event_replay_failed"})
        return {
            "passed": not issues,
            "sequence": state["last_sequence"],
            "issues": issues,
            "scope": "journal hashes, balanced postings, cash and lot checks, full event replay; not external statement verification",
        }
