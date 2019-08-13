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


