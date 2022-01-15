"""Plan state-aware target-inventory orders, then replay through the journal engine."""

import copy
from decimal import Decimal

from .execution_book import ExecutionBook, LIVE
from .execution_clock import timeline_groups
from .execution_engine import simulate_execution
from .execution_model import compile_execution
from .instruments import timestamp, timestamp_text
from .market_model import canonical, digest
from .money import ZERO, arithmetic, text
from .strategy_inputs import prepare_strategy_inputs

ASSUMPTIONS = [
    "Signals use each decision's own historical universe and bar-vintage snapshots, gated by the explicitly selected publication or recording clock.",
    "Long-only target inventory is the declared fixed quantity when the last eligible close is strictly above its trailing mean, otherwise zero; this is a reproducible control strategy, not a return claim.",
    "Missing or stale features use the explicit hold/exit policy. Leaving the historical universe targets zero; inactive instruments remain visible and cannot receive a fabricated liquidation.",
    "Decisions observe actual prior fills and settled quote-currency cash. Market IOC orders are submitted for the remaining inventory difference; costs and liquidity can prevent target attainment.",
    "An existing live order defers a new order for that instrument until a later decision; a changed signal does not retroactively cancel a pending first-open execution.",
    "At a shared instant expiry and closes precede decisions, and decisions precede opens. Submission is never eligible for an open at the identical timestamp.",
    "The declared allocation order breaks ties among same-decision submissions; older pending orders retain submission-time priority. Simultaneous sells do not pre-fund earlier buys unless that ordering permits it.",
    "Execution prices are a separate declared realization vintage and are never supplied to the signal calculator. Raw-price corporate actions and market/settlement calendars are not inferred.",
    "Snapshot hashes prove portable content integrity, not source authenticity, market-data licensing or completeness of an external provider's history.",
]


