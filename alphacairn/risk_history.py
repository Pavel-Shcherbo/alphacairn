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


def observation_returns(history, factors, configuration, spec):
    observations = []
    excluded = []
    points = history["observations"]
    start = configuration["history_start"]
    end = configuration["history_end"]
    asof = configuration["as_of"]
    for left, right in zip(points, points[1:]):
        reasons = []
        if left["at"] < start or right["at"] > end:
            reasons.append({"code": "outside_window"})
        if left["available_at"] > asof or right["available_at"] > asof:
            reasons.append({"code": "not_available_as_of"})
        if timestamp(right["at"]) - timestamp(left["at"]) > timedelta(
            days=configuration["max_gap_days"]
        ):
            reasons.append({"code": "observation_gap"})
        levels = []
        for factor in factors:
            pair = []
            for point in (left, right):
                price = (
                    point["prices"].get(factor["instrument"])
                    if factor["instrument"] is not None
                    else "1"
                )
                rate = (
                    point["fx"].get(factor["currency"])
                    if factor["currency"] != spec.base_currency
                    else "1"
                )
                if price is None or rate is None:
                    reasons.append(
                        {
                            "code": "missing_history_value",
                            "at": point["at"],
                            "factor": factor["id"],
                        }
                    )
                    pair.append(None)
                else:
                    pair.append(Fraction(price) * Fraction(rate))
            levels.append(pair)
        if reasons:
            excluded.append({"from": left["at"], "to": right["at"], "reasons": reasons})
            continue
        changes = [quantized_return(pair[1] / pair[0] - 1) for pair in levels]
        observations.append(
            {
                "from": left["at"],
                "to": right["at"],
                "returns": changes,
                "pnl": sum(
                    (
                        factor["base_value"] * change
                        for factor, change in zip(factors, changes)
                    ),
                    Fraction(),
                ),
            }
        )
    return observations, excluded


def history_report(observations, excluded, factors, configuration):
    return {
        "source_observation_count": (
            len(observations) + len(excluded) + 1 if observations or excluded else 0
        ),
        "used_return_count": len(observations),
        "window_start": configuration["history_start"],
        "window_end": configuration["history_end"],
        "effective_start": observations[0]["from"] if observations else None,
        "effective_end": observations[-1]["to"] if observations else None,
        "minimum_required": configuration["min_observations"],
        "excluded_intervals": excluded,
        "factors": [
            {
                "id": f["id"],
                "instrument": f["instrument"],
                "currency": f["currency"],
                "base_value": fixed(f["base_value"]),
            }
            for f in factors
        ],
        "intervals": [
            {
                "from": row["from"],
                "to": row["to"],
                "returns": {
                    factor["id"]: fixed(change, 12)
                    for factor, change in zip(factors, row["returns"])
                },
                "pnl": fixed(row["pnl"]),
            }
            for row in observations
        ],
        "policy": "Adjacent complete observations only; no forward filling, no joining over gaps; split-adjusted price-only levels and base-per-quote FX; returns rounded half-even to 12 decimal places",
    }
