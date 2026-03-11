"""Independent minor-unit, business-day and crash controls for cash settlement."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_model import compile_execution
from alphacairn.execution_export import write_execution, verify_execution_bundle
from alphacairn.instruments import AccountSpec
from alphacairn.ledger import Ledger
from alphacairn.market_model import canonical, digest
from alphacairn.market_store import MarketCatalog
from alphacairn.risk_positions import exposures, stress_portfolio
from alphacairn.risk_history import factor_exposures
from alphacairn.risk_journal import capture_journal
from alphacairn.session_model import build_calendar
from alphacairn.settlement_clock import SettlementClock
from alphacairn.settlement_service import SettlementService
from alphacairn.strategy_inputs import capture_strategy
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_bundle import write_strategy, verify_strategy_bundle
from alphacairn.study_model import trial_contract
from alphacairn.valuation import value_portfolio
from test_corporate import split, dividend
from test_strategy import load


def control():
    return load("settlement-execution.json")


