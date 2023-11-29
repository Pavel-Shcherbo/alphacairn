"""Signed historical losses with nearest-rank VaR and fractional-mass tail ES."""

from fractions import Fraction
import math

from .risk_numbers import exact, fixed


def historical_tail(observations, confidence, equity):
    if not observations:
        raise ValueError("historical tail risk requires observed shocks")
    confidence = Fraction(confidence)
    ordered = sorted(
        (
            {"loss": -row["pnl"], "from": row["from"], "to": row["to"]}
            for row in observations
        ),
        key=lambda row: (row["loss"], row["from"], row["to"]),
    )
    count = len(ordered)
    index = math.ceil(confidence * count) - 1
    var = ordered[index]["loss"]
    mass = (1 - confidence) * count
    remaining = mass
    total = Fraction()
    tail = []
    for row in reversed(ordered):
        if remaining <= 0:
            break
        weight = min(Fraction(1), remaining)
        remaining -= weight
        total += row["loss"] * weight
        tail.append(
            {
                "from": row["from"],
                "to": row["to"],
                "loss": fixed(row["loss"]),
                "observation_weight": fixed(weight),
                "observation_weight_exact": exact(weight),
            }
        )
    es = total / mass
    return {
        "confidence": fixed(confidence),
        "observations": count,
        "var_rank": index + 1,
        "value_at_risk_base": fixed(var),
        "value_at_risk_base_exact": exact(var),
        "expected_shortfall_base": fixed(es),
        "expected_shortfall_base_exact": exact(es),
        "value_at_risk_fraction": fixed(var / equity),
        "expected_shortfall_fraction": fixed(es / equity),
        "tail_observation_mass": fixed(mass),
        "tail_observation_mass_exact": exact(mass),
        "tail": tail,
        "method": "Loss = negative static-exposure historical P&L. VaR is ceil(confidence*n) in ascending losses; ES integrates the worst (1-confidence)*n observation mass with a fractional boundary. Equal observation weights; signed gains are not floored at zero.",
    }
