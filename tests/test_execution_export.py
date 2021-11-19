"""Deterministic portable execution evidence, tampering and CLI lifecycle."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alphacairn.execution_engine import simulate_execution
from alphacairn.execution_export import verify_execution_bundle, write_execution
from test_execution import scenario


class ExecutionExportTests(unittest.TestCase):
    pass
