"""Freeze decision-time market vintages separately from execution realizations."""

import copy
from dataclasses import dataclass
from decimal import Decimal

from .execution_model import ExecutionPlan, compile_execution
from .instruments import AccountSpec, timestamp, timestamp_text
from .market_model import (
    MAX_BYTES,
    canonical,
    day,
    digest,
    identifier,
    instant,
    validate_query,
    verify_snapshot,
)
from .money import aligned, arithmetic, decimal_value, text

EXECUTION_FIELDS = {
    "version",
    "account",
    "starts_at",
    "ends_at",
    "initial_cash",
    "fees",
    "slippage_bps",
    "max_mark_age_seconds",
    "fx",
}
CONFIG_FIELDS = {
    "version",
    "source",
    "universe",
    "clock",
    "history_start",
    "lookback",
    "max_feature_age_seconds",
    "decisions",
    "market_cutoff",
    "execution_sessions",
    "execution",
    "liquidity",
    "target_quantities",
    "allocation_order",
    "missing_signal_policy",
}


