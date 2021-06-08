"""Simulate bounded order scenarios and reconcile fills through the portfolio journal."""

import itertools
import tempfile
from decimal import Decimal
from pathlib import Path

from .execution_book import ExecutionBook, LIVE
from .execution_model import ExecutionPlan, compile_execution
from .execution_money import marked_value
from .ledger import Ledger
from .market_model import canonical, digest
from .money import ZERO, arithmetic, text
from .valuation import value_portfolio

ASSUMPTIONS = [
    "Long-only spot positions and settled cash per quote currency; no borrowing, shorting or automatic FX exchange.",
    "Orders become fill-eligible only at an instrument bar whose open is strictly later than submission.",
    "At a shared instant, explicit expiry precedes close fills; close processing precedes new commands and opens.",
    "Across instruments sharing an execution phase, submission time and input command order determine cash allocation.",
    "Market and marketable-limit fills use the open with adverse tick-rounded slippage; limits cap the execution price.",
    "Other limit touches are modeled at the limit on bar close, without asserting an observed intrabar path.",
    "Liquidity is a separately supplied pre-open known quantity budget shared by both sides and phases; it is not realized daily volume.",
    "IOC remainder cancels after its first eligible open; DAY remainder cancels after its first eligible bar closes; GTC remainder persists.",
    "Cancellation requests take effect at the next instrument open strictly after the request, including requests made during a bar.",
    "Each partial fill incurs its own percentage/minimum fee, rounded half-even in quote currency.",
    "Pending orders reserve neither cash nor shares; actual balances and positions are checked immediately before each fill.",
    "Positions are marked without forced final liquidation. Missing or stale marks/FX produce incomplete equity rather than zero.",
    "FX rates mean base currency units per one quote currency unit; each cash/position component converts with half-even rounding.",
    "Submitted commands, liquidity knowledge times and prices are caller-declared inputs, not authenticated historical evidence.",
]


def simulate_execution(definition, *, should_cancel=None):
    if should_cancel is not None and not callable(should_cancel):
        raise ValueError("execution cancellation must be callable")
    plan = (
        definition
        if isinstance(definition, ExecutionPlan)
        else compile_execution(definition)
    )
    if (
        digest(plan.definition) != plan.sha256
        or plan.account.definition() != plan.definition["account"]
    ):
        raise ValueError("compiled execution plan was mutated after validation")
    with arithmetic():
        return _simulate(plan, should_cancel)


