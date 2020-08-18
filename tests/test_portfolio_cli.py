import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alphacairn.portfolio import read_json

ROOT = Path(__file__).resolve().parents[1]


class PortfolioCliTests(unittest.TestCase):
    def call(self, db, *arguments):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "alphacairn.portfolio",
                "--db",
                str(db),
                *map(str, arguments),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

