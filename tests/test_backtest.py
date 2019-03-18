import math
import tempfile
import unittest
from pathlib import Path

from alphacairn.backtest import load_bars, simulate


def bars(closes):
    return [
        {"date": f"2020-01-{i+1:02d}", "open": 100.0, "close": float(value)}
        for i, value in enumerate(closes)
    ]


class BacktestTests(unittest.TestCase):
    pass
