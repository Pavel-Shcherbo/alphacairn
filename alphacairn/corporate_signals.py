"""Known-at-decision split factors over original captured unadjusted closes."""

from decimal import Decimal
from fractions import Fraction

from .instruments import timestamp
from .money import arithmetic, text


def signal_prices(actions, instrument, rows, decision):
    when = timestamp(decision["at"])
    selected = [
        item
        for item in actions
        if item["kind"] == "split"
        and item["instrument"] == instrument
        and timestamp(item["at"]) <= when
        and timestamp(item["known_at"]) <= when
    ]
    prices = []
    used = set()
    for row in rows:
        observation = row["observation"]
        closed = timestamp(observation["closed_at"])
        value = Fraction(observation["close"])
        for action in selected:
            if closed <= timestamp(action["at"]):
                value *= Fraction(action["denominator"], action["numerator"])
                used.add(action["id"])
        if value.numerator.bit_length() > 8192 or value.denominator.bit_length() > 8192:
            raise ValueError(
                "split-normalized signal exceeds rational precision budget"
            )
        prices.append(value)
    return prices, sorted(used)


def fraction_text(value):
    with arithmetic():
        return text(Decimal(value.numerator) / Decimal(value.denominator))
