import math
import statistics
import unittest
from datetime import date, timedelta

from alphacairn.analytics import (
    block_resample,
    compare,
    drawdown_history,
    period_returns,
    quantile,
    rolling_volatility,
    summarize,
)


