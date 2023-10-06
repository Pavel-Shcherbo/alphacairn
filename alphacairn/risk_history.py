"""Complete-case adjacent shock observations without bridging missing inputs."""

from datetime import timedelta
from fractions import Fraction

from .instruments import timestamp
from .risk_model import MAX_FACTORS
from .risk_numbers import fixed, quantized_return


def factor_exposures(rows, spec):
    factors = {}
    for row in rows:
        amount = Fraction(row["base_value"])
        if not amount:
            continue
        if row["instrument"] is not None:
            key = "asset:" + row["instrument"]
            item = {
                "id": key,
                "instrument": row["instrument"],
                "currency": row["currency"],
                "base_value": Fraction(),
            }
        elif row["currency"] != spec.base_currency:
            key = "fx:" + row["currency"]
            item = {
                "id": key,
                "instrument": None,
                "currency": row["currency"],
                "base_value": Fraction(),
            }
        else:
            continue
        if key not in factors:
            factors[key] = item
        factors[key]["base_value"] += amount
    if len(factors) > MAX_FACTORS:
        raise ValueError("risk estimation supports at most 24 active asset/FX factors")
    return [factors[key] for key in sorted(factors)]


