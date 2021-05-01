"""Run or independently replay a local multi-instrument order scenario."""

import argparse
import json
import sqlite3
from pathlib import Path

from .execution_engine import simulate_execution
from .execution_export import parse_data, verify_execution_bundle, write_execution


