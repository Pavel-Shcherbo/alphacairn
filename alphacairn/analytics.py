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


