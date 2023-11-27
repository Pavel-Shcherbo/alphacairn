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


def exposures(state, valuation, spec):
    if not valuation["complete"]:
        return []
    result = []
    for row in valuation["positions"]:
        instrument = spec.instrument(row["instrument"])
        result.append(
            {
                "id": "asset:" + instrument.id,
                "kind": "position",
                "instrument": instrument.id,
                "currency": instrument.quote_currency,
                "venue": instrument.venue,
                "asset_kind": instrument.kind,
                "base_value": row["base_value"],
            }
        )
    for row in valuation["cash"]:
        result.append(
            {
                "id": "cash:" + row["currency"],
                "kind": "cash",
                "instrument": None,
                "currency": row["currency"],
                "venue": None,
                "asset_kind": "cash",
                "base_value": row["base_value"],
            }
        )
    for row in valuation.get("dividend_receivables", []):
        result.append(
            {
                "id": "dividend:" + row["accrual_id"],
                "kind": "dividend_receivable",
                "instrument": None,
                "currency": row["currency"],
                "venue": None,
                "asset_kind": "dividend_receivable",
                "base_value": row["base_value"],
            }
        )
    if sum((Fraction(row["base_value"]) for row in result), Fraction()) != Fraction(
        valuation["equity"]
    ):
        raise ValueError("risk exposures do not reconcile to journal valuation")
    return sorted(result, key=lambda row: row["id"])


def concentrations(rows, equity, limits):
    if equity is None or Fraction(equity) <= 0:
        return {"complete": False, "groups": {}, "breaches": []}
    groups = {"instrument": {}, "currency": {}, "venue": {}, "kind": {}}
    for row in rows:
        for group, key in [
            ("instrument", "instrument"),
            ("currency", "currency"),
            ("venue", "venue"),
            ("kind", "asset_kind"),
        ]:
            label = row[key]
            if label is not None:
                groups[group][label] = groups[group].get(label, Fraction()) + Fraction(
                    row["base_value"]
                )
    result = {}
    breaches = []
    for group, values in groups.items():
        result[group] = []
        for label, value in sorted(values.items()):
            share = value / Fraction(equity)
            row = {
                "name": label,
                "base_value": fixed(value),
                "weight": fixed(share),
                "limit": limits[group],
                "breached": share > Fraction(limits[group]),
            }
            result[group].append(row)
            if row["breached"]:
                breaches.append({"group": group, **row})
    return {
        "complete": True,
        "groups": result,
        "breaches": breaches,
        "denominator": "total marked equity including cash and dividend assets",
    }


def stress_portfolio(state, quotes, configuration, baseline, spec):
    results = []
    for scenario in configuration["scenarios"]:
        if not baseline["complete"]:
            results.append(
                {
                    "id": scenario["id"],
                    "complete": False,
                    "equity": None,
                    "pnl": None,
                    "missing_inputs": baseline["missing_inputs"],
                }
            )
            continue
        marks = copy.deepcopy(quotes["marks"])
        fx = copy.deepcopy(quotes["fx"])
        with arithmetic():
            for name, shock in scenario["price_shocks"].items():
                if name in marks:
                    value = Decimal(marks[name]["price"]) * (1 + Decimal(shock))
                    marks[name]["price"] = text(
                        decimal_value(
                            rounded(value, 18).normalize(),
                            "stressed mark",
                            nonnegative=True,
                        )
                    )
            for currency, shock in scenario["fx_shocks"].items():
                if currency in fx:
                    value = Decimal(fx[currency]["rate"]) * (1 + Decimal(shock))
                    fx[currency]["rate"] = text(
                        decimal_value(
                            rounded(value, 18).normalize(), "stressed FX", positive=True
                        )
                    )
            valued = value_portfolio(
                state,
                marks,
                fx,
                as_of=configuration["as_of"],
                max_age_seconds=configuration["max_age_seconds"],
            )
        changes = []
        for section, key in [
            ("positions", "instrument"),
            ("cash", "currency"),
            ("dividend_receivables", "accrual_id"),
        ]:
            before = {row[key]: row for row in baseline.get(section, [])}
            for row in valued.get(section, []):
                origin = before[row[key]]
                changes.append(
                    {
                        "kind": section,
                        "id": row[key],
                        "before": origin["base_value"],
                        "after": row["base_value"],
                        "pnl": fixed(
                            Fraction(row["base_value"]) - Fraction(origin["base_value"])
                        ),
                    }
                )
        pnl = Fraction(valued["equity"]) - Fraction(baseline["equity"])
        if sum((Fraction(row["pnl"]) for row in changes), Fraction()) != pnl:
            raise ValueError("stress components do not reconcile")
        held = set(state["positions"])
        currencies = {
            row["currency"] for row in baseline["cash"] if Fraction(row["amount"])
        }
        currencies.update(spec.instrument(name).quote_currency for name in held)
        currencies.update(
            row["currency"] for row in baseline.get("dividend_receivables", [])
        )
        results.append(
            {
                "id": scenario["id"],
                "complete": True,
                "equity": valued["equity"],
                "pnl": fixed(pnl),
                "return": (
                    fixed(pnl / Fraction(baseline["equity"]))
                    if Fraction(baseline["equity"])
                    else None
                ),
                "components": changes,
                "unused_price_shocks": sorted(set(scenario["price_shocks"]) - held),
                "unused_fx_shocks": sorted(set(scenario["fx_shocks"]) - currencies),
            }
        )
    return results
