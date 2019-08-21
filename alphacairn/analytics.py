"""Descriptive risk statistics under declared bar-frequency assumptions."""

import math
import random
import statistics
from collections import deque
from datetime import date


def finite(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def frequency(periods_per_year):
    if type(periods_per_year) is not int or not 1 <= periods_per_year <= 366:
        raise ValueError(
            "periods_per_year must be an integer between 1 and 366 for daily bars"
        )
    return periods_per_year


def quantile(values, probability):
    finite(probability, "probability")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between zero and one")
    if not values:
        raise ValueError("quantile requires observations")
    ordered = sorted(finite(value, "observation") for value in values)
    position = (len(ordered) - 1) * probability
    left = int(math.floor(position))
    right = int(math.ceil(position))
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def period_returns(equity, initial_cash):
    previous = finite(initial_cash, "initial_cash", positive=True)
    if not equity:
        raise ValueError("equity history must not be empty")
    result, previous_day = [], None
    for item in equity:
        day = date.fromisoformat(item["date"])
        if previous_day is not None and day <= previous_day:
            raise ValueError("equity dates must be strictly increasing")
        current = finite(item["equity"], "equity", positive=True)
        change = current / previous - 1
        if not math.isfinite(change) or change <= -1:
            raise ValueError("period return exceeds the supported finite range")
        result.append(change)
        previous, previous_day = current, day
    return result


def drawdown_history(equity, initial_cash):
    period_returns(equity, initial_cash)
    peak, peak_day = float(initial_cash), None
    current, episodes = None, []
    series, duration = [], 0
    for item in equity:
        value, day = item["equity"], item["date"]
        if value >= peak:
            if current is not None:
                current["recovery_date"] = day
                current["recovered"] = True
                episodes.append(current)
                current = None
            peak, peak_day, duration = value, day, 0
        else:
            duration += 1
            depth = 1 - value / peak
            if current is None:
                current = {
                    "peak_date": peak_day,
                    "first_underwater_date": day,
                    "trough_date": day,
                    "depth": depth,
                    "underwater_bars": 0,
                    "recovery_date": None,
                    "recovered": False,
                }
            current["underwater_bars"] += 1
            if depth > current["depth"]:
                current["depth"], current["trough_date"] = depth, day
        series.append(
            {"date": day, "drawdown": 1 - value / peak, "underwater_bars": duration}
        )
    if current is not None:
        episodes.append(current)
    return {
        "series": series,
        "episodes": episodes,
        "maximum": max(row["drawdown"] for row in series),
        "longest_underwater_bars": max(row["underwater_bars"] for row in series),
    }


