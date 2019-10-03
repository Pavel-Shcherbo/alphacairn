import unittest
from datetime import date, timedelta

from alphacairn.backtest import simulate
from alphacairn.walkforward import walk_forward


def bars(count=80):
    result = []
    price = 100.0
    for index in range(count):
        close = price * (1.01 if index % 7 < 4 else 0.985)
        result.append(
            {
                "date": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
                "open": price,
                "close": close,
            }
        )
        price = close
    return result


class WalkForwardTests(unittest.TestCase):
    pass
