"""Current marked exposures, concentration groups and exactly reconciled stresses."""

import copy
from decimal import Decimal
from fractions import Fraction

from .money import arithmetic, rounded, text, decimal_value
from .risk_numbers import fixed
from .valuation import value_portfolio


def validate_quotes(value, configuration):
    if not isinstance(value, dict) or set(value) != {
        "as_of",
        "marks",
        "fx",
        "max_age_seconds",
    }:
        raise ValueError("risk quotes require as_of, marks, fx and max_age_seconds")
    from .instruments import timestamp, timestamp_text

    result = copy.deepcopy(value)
    result["as_of"] = timestamp_text(timestamp(value["as_of"]))
    if (
        result["as_of"] != configuration["as_of"]
        or value["max_age_seconds"] != configuration["max_age_seconds"]
        or type(value["max_age_seconds"]) is not int
    ):
        raise ValueError("quote clock/age must equal the risk configuration")
    return result


