import hashlib
import io
from pathlib import Path

from .backtest import parse_bars, simulate
from .httpapp import serve

ROOT = Path(__file__).resolve().parents[1]


def example():
    return {
        "csv": (ROOT / "examples/synthetic.csv").read_text(),
        "source": "Synthetic daily fixture; not market data",
    }


