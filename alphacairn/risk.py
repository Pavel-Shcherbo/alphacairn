"""Capture, analyze and replay portable multi-asset risk studies."""

import argparse
import json
from pathlib import Path
import sqlite3

from .market_model import decode
from .risk_bundle import save_risk_inputs, write_risk, verify_risk_bundle
from .risk_engine import analyze_risk
from .risk_inputs import capture_risk_inputs
from .risk_model import MAX_INPUT, bounded_json


