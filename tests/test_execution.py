"""Hand-calculated execution controls independent of descriptive strategy metrics."""

import copy
import tempfile
import unittest
from decimal import Decimal, localcontext, Inexact
from pathlib import Path

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_model import compile_execution


def instrument(name="A", currency="USD", step="1", tick="0.01"):
    return {
        "id": name,
        "symbol": name,
        "venue": "DEMO",
        "kind": "equity",
        "quote_currency": currency,
        "quantity_step": step,
        "price_tick": tick,
    }


def bar(day=2, name="A", opening="10", close="11", low="8", high="12", liquidity="100"):
    session = f"2020-01-{day:02d}"
    return {
        "instrument": name,
        "session": session,
        "opened_at": session + "T09:00:00Z",
        "closed_at": session + "T17:00:00Z",
        "open": opening,
        "high": high,
        "low": low,
        "close": close,
        "liquidity": liquidity,
        "liquidity_known_at": session + "T08:00:00Z",
    }


def order(
    name="buy",
    quantity="5",
    side="buy",
    kind="market",
    limit=None,
    tif="GTC",
    at="2020-01-01T12:00:00Z",
    asset="A",
    expires=None,
):
    return {
        "action": "submit",
        "id": name,
        "at": at,
        "instrument": asset,
        "side": side,
        "kind": kind,
        "quantity": quantity,
        "limit": limit,
        "time_in_force": tif,
        "expires_at": expires,
    }


def scenario():
    return {
        "version": 1,
        "account": {
            "name": "execution",
            "base_currency": "USD",
            "currencies": {"USD": 2},
            "instruments": [instrument()],
        },
        "starts_at": "2020-01-01T00:00:00Z",
        "ends_at": "2020-01-04T17:00:00Z",
        "initial_cash": {"USD": "100"},
        "fees": {"rate_bps": "0", "minimum": {}},
        "slippage_bps": "0",
        "max_mark_age_seconds": 86400 * 5,
        "bars": [bar()],
        "commands": [order()],
        "fx": [],
    }


class ExecutionTests(unittest.TestCase):
    pass
