"""Daily-bar simulator: previous-close signals, next-open execution."""

import csv
import math
from datetime import date


def parse_bars(stream):
    rows = list(csv.DictReader(stream))
    bars, previous = [], None
    for row in rows:
        day = date.fromisoformat(row["date"])
        opening, close = float(row["open"]), float(row["close"])
        if previous is not None and day <= previous:
            raise ValueError("bar dates must be strictly increasing")
        if not all(math.isfinite(x) and x > 0 for x in [opening, close]):
            raise ValueError("prices must be positive and finite")
        bars.append({"date": day.isoformat(), "open": opening, "close": close})
        previous = day
    if len(bars) < 2:
        raise ValueError("at least two bars are required")
    return bars


