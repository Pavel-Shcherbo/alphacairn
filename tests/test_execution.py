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


