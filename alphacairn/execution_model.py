"""Bounded multi-instrument execution scenarios with explicit bar-clock contracts."""

import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .instruments import AccountSpec, identity, timestamp, timestamp_text
from .market_model import canonical, digest
from .money import arithmetic, aligned, decimal_value, exact_amount, text


@dataclass(frozen=True)
class ExecutionPlan:
    definition: dict
    account: AccountSpec
    sha256: str


def compile_execution(definition):
    # JSON serialization rejects non-finite values before domain conversion.
    try:
        raw = canonical(definition)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("execution scenario must be finite bounded JSON") from error
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("execution scenario exceeds 8 MiB")
    required = {
        "version",
        "account",
        "starts_at",
        "ends_at",
        "initial_cash",
        "fees",
        "slippage_bps",
        "max_mark_age_seconds",
        "bars",
        "commands",
        "fx",
    }
    version = definition.get("version") if isinstance(definition, dict) else None
    if type(version) is int and version == 2:
        required |= {"calendar", "calendar_policy"}
    if (
        not isinstance(definition, dict)
        or set(definition) != required
        or type(definition["version"]) is not int
        or definition["version"] not in (1, 2)
    ):
        raise ValueError(
            "execution requires version 1 or 2 and explicit account/time/cost/data/command fields"
        )
    account = AccountSpec.compile(definition["account"])
    currencies = dict(account.currencies)
    start = timestamp(definition["starts_at"])
    end = timestamp(definition["ends_at"])
    if start >= end:
        raise ValueError("execution start must precede end")
    cash = definition["initial_cash"]
    if not isinstance(cash, dict) or not set(cash) <= set(currencies):
        raise ValueError("initial cash uses only declared currencies")
    fees = definition["fees"]
    if (
        not isinstance(fees, dict)
        or set(fees) != {"rate_bps", "minimum"}
        or not isinstance(fees["minimum"], dict)
        or not set(fees["minimum"]) <= set(currencies)
    ):
        raise ValueError("fees require rate_bps and per-currency minimum")
    with arithmetic():
        rate = decimal_value(fees["rate_bps"], "fee bps", nonnegative=True)
        slip = decimal_value(
            definition["slippage_bps"], "slippage bps", nonnegative=True
        )
        if rate >= 10000 or slip >= 10000:
            raise ValueError("cost rates must be below 10,000 bps")
        normalized_cash = {
            code: text(
                exact_amount(
                    cash.get(code, "0"), places, "initial cash", nonnegative=True
                )
            )
            for code, places in account.currencies
        }
        minimum = {
            code: text(
                exact_amount(
                    fees["minimum"].get(code, "0"),
                    places,
                    "minimum fee",
                    nonnegative=True,
                )
            )
            for code, places in account.currencies
        }
    max_age = definition["max_mark_age_seconds"]
    if type(max_age) is not int or not 0 <= max_age <= 366 * 86400:
        raise ValueError("max mark age must be 0–366 days in seconds")
    bars = definition["bars"]
    if not isinstance(bars, list) or not 1 <= len(bars) <= 10000:
        raise ValueError("execution requires 1–10,000 bars")
    normalized_bars = []
    by_instrument = {}
    bar_keys = set()
    with arithmetic():
        for item in bars:
            if not isinstance(item, dict) or set(item) != {
                "instrument",
                "session",
                "opened_at",
                "closed_at",
                "open",
                "high",
                "low",
                "close",
                "liquidity",
                "liquidity_known_at",
            }:
                raise ValueError(
                    "execution bar fields do not match the clock/liquidity contract"
                )
            instrument = account.instrument(item["instrument"])
            opened = timestamp(item["opened_at"])
            closed = timestamp(item["closed_at"])
            known = timestamp(item["liquidity_known_at"])
            if not start <= opened < closed <= end or known > opened:
                raise ValueError(
                    "bars require start <= open < close <= end and liquidity known by open"
                )
            instrument.require_active(opened)
            if instrument.active_until is not None and closed > instrument.active_until:
                raise ValueError("bar extends beyond instrument active interval")
            session = item["session"]
            if (
                not isinstance(session, str)
                or len(session) != 10
                or date.fromisoformat(session).isoformat() != session
            ):
                raise ValueError("bar session requires YYYY-MM-DD")
            key = (instrument.id, session)
            if key in bar_keys:
                raise ValueError("execution supports one bar per instrument/session")
            bar_keys.add(key)
            prices = {
                field: aligned(item[field], instrument.price_tick, field)
                for field in ["open", "high", "low", "close"]
            }
            if (
                not prices["low"]
                <= min(prices["open"], prices["close"])
                <= max(prices["open"], prices["close"])
                <= prices["high"]
            ):
                raise ValueError("execution OHLC envelope is inconsistent")
            liquidity = decimal_value(item["liquidity"], "liquidity", nonnegative=True)
            normalized_bars.append(
                {
                    "instrument": instrument.id,
                    "session": session,
                    "opened_at": timestamp_text(opened),
                    "closed_at": timestamp_text(closed),
                    "liquidity_known_at": timestamp_text(known),
                    "liquidity": text(liquidity),
                    **{key: text(value) for key, value in prices.items()},
                }
            )
            by_instrument.setdefault(instrument.id, []).append((opened, closed))
    for intervals in by_instrument.values():
        intervals.sort()
        if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
            raise ValueError("bars for one instrument cannot overlap")
    commands = definition["commands"]
    if not isinstance(commands, list) or len(commands) > 2000:
        raise ValueError("execution supports at most 2,000 commands")
    normalized_commands = []
    command_ids = set()
    orders = {}
    previous = start
    order_counts = {}
    with arithmetic():
        for sequence, item in enumerate(commands):
            if not isinstance(item, dict) or item.get("action") not in (
                "submit",
                "cancel",
            ):
                raise ValueError("command requires submit or cancel action")
            label = identity(item.get("id"), "command ID")
            when = timestamp(item.get("at"))
            if label in command_ids or not previous <= when <= end:
                raise ValueError(
                    "command IDs must be unique and times nondecreasing inside the scenario"
                )
            command_ids.add(label)
            previous = when
            if item["action"] == "cancel":
                if set(item) != {"action", "id", "at", "order_id"}:
                    raise ValueError("cancel requires action, id, at and order_id")
                target = item["order_id"]
                if not isinstance(target, str) or target not in orders:
                    raise ValueError("cancel must reference an earlier submitted order")
                normalized_commands.append(
                    {
                        "action": "cancel",
                        "id": label,
                        "at": timestamp_text(when),
                        "order_id": target,
                    }
                )
                continue
            required_order = {
                "action",
                "id",
                "at",
                "instrument",
                "side",
                "kind",
                "quantity",
                "time_in_force",
            }
            if set(item) - required_order - {
                "limit",
                "expires_at",
            } or not required_order <= set(item):
                raise ValueError("submit contains missing or unsupported order fields")
            instrument = account.instrument(item["instrument"])
            instrument.require_active(when)
            if (
                item["side"] not in ("buy", "sell")
                or item["kind"] not in ("market", "limit")
                or item["time_in_force"] not in ("GTC", "IOC", "DAY")
            ):
                raise ValueError("unsupported side, order kind or time in force")
            quantity = aligned(
                item["quantity"], instrument.quantity_step, "order quantity"
            )
            limit = (
                aligned(item.get("limit"), instrument.price_tick, "limit price")
                if item["kind"] == "limit"
                else None
            )
            if item["kind"] == "market" and item.get("limit") is not None:
                raise ValueError("market orders cannot declare a limit price")
            expiry = (
                timestamp(item["expires_at"])
                if item.get("expires_at") is not None
                else None
            )
            if expiry is not None and expiry <= when:
                raise ValueError("order expiry must follow submission")
            if instrument.active_until is not None:
                expiry = (
                    min(expiry, instrument.active_until)
                    if expiry is not None
                    else instrument.active_until
                )
            normalized = {
                "action": "submit",
                "id": label,
                "at": timestamp_text(when),
                "instrument": instrument.id,
                "side": item["side"],
                "kind": item["kind"],
                "quantity": text(quantity),
                "limit": text(limit) if limit is not None else None,
                "time_in_force": item["time_in_force"],
                "expires_at": timestamp_text(expiry) if expiry is not None else None,
            }
            orders[label] = normalized
            normalized_commands.append(normalized)
            order_counts[instrument.id] = order_counts.get(instrument.id, 0) + 1
    if len(orders) > 1000:
        raise ValueError("execution supports at most 1,000 orders")
    work = sum(
        len(intervals) * order_counts.get(name, 0)
        for name, intervals in by_instrument.items()
    )
    if work > 2_000_000:
        raise ValueError(
            "scenario exceeds two million order/bar evaluations; partition the study"
        )
    quotes = definition["fx"]
    if not isinstance(quotes, list) or len(quotes) > 10000:
        raise ValueError("execution supports at most 10,000 explicit FX observations")
    normalized_fx = []
    seen_fx = set()
    with arithmetic():
        for item in quotes:
            if not isinstance(item, dict) or set(item) != {"currency", "at", "rate"}:
                raise ValueError("FX observations require currency, at and rate")
            currency = item["currency"]
            account.places(currency)
            when = timestamp(item["at"])
            value = decimal_value(item["rate"], "FX rate", positive=True)
            if (
                not start <= when <= end
                or currency == account.base_currency
                and value != 1
            ):
                raise ValueError("FX time or base-currency rate is invalid")
            key = (currency, when)
            if key in seen_fx:
                raise ValueError("duplicate currency/FX time")
            seen_fx.add(key)
            normalized_fx.append(
                {"currency": currency, "at": timestamp_text(when), "rate": text(value)}
            )
    result = {
        "version": version,
        "account": account.definition(),
        "starts_at": timestamp_text(start),
        "ends_at": timestamp_text(end),
        "initial_cash": normalized_cash,
        "fees": {"rate_bps": text(rate), "minimum": minimum},
        "slippage_bps": text(slip),
        "max_mark_age_seconds": max_age,
        "bars": sorted(
            normalized_bars, key=lambda row: (row["opened_at"], row["instrument"])
        ),
        "commands": normalized_commands,
        "fx": sorted(normalized_fx, key=lambda row: (row["at"], row["currency"])),
    }
    if version == 2:
        from .session_calendar import validate_execution_calendar

        result["calendar"] = copy.deepcopy(definition["calendar"])
        result["calendar_policy"] = copy.deepcopy(definition["calendar_policy"])
        validate_execution_calendar(result, account)
    return ExecutionPlan(copy.deepcopy(result), account, digest(result))
