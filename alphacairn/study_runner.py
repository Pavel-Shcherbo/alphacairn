"""Execute registered frozen inputs without discarding failed or incomplete trials."""

from fractions import Fraction
import json
import sqlite3
import uuid

from .market_model import canonical, digest
from .risk_engine import analyze_risk
from .risk_numbers import fixed
from .strategy_engine import simulate_strategy
from .study_model import trial_contract
from .study_store import TERMINAL, decode, trial_meta


