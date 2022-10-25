"""Clock, coverage and offline controls against hand-calculated session instants."""

import base64
import copy
import datetime as dt
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_export import write_execution, verify_execution_bundle
from alphacairn.execution_model import compile_execution
from alphacairn.market_model import canonical, digest
from alphacairn.session_calendar import SessionCalendar
from alphacairn.session_model import build_calendar, verify_calendar
from alphacairn.session_zones import check_tzif, zone_key
from test_execution import scenario, bar
from test_strategy import load
from alphacairn.strategy_inputs import capture_strategy
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_bundle import write_strategy, verify_strategy_bundle
from alphacairn.market_store import MarketCatalog


