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


