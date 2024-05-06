"""Explicit development/holdout windows and frozen research-method identities."""

import copy

from .instruments import identity, timestamp, timestamp_text
from .market_model import canonical, digest
from .risk_inputs import prepare_risk_inputs
from .strategy_inputs import prepare_strategy_inputs

MAX_INPUT = 16 * 1024 * 1024


