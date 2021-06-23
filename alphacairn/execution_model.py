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


