import hashlib
import io
from pathlib import Path

from .backtest import parse_bars, simulate
from .httpapp import serve

ROOT = Path(__file__).resolve().parents[1]


