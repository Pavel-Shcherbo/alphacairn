"""Command-line descriptive analytics and sequential strategy evaluation."""

import argparse
import hashlib
import json
from pathlib import Path

from .analytics import (
    block_resample,
    compare,
    drawdown_history,
    rolling_volatility,
    summarize,
)
from .backtest import dataset_digest, load_bars, simulate
from .walkforward import walk_forward


