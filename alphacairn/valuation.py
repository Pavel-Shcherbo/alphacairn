"""Explicit as-of marks and FX conversion for a current journal state."""

from decimal import Decimal

from .corporate_accounts import dividend_assets
from .instruments import AccountSpec, timestamp, timestamp_text
from .money import arithmetic, ZERO, decimal_value, rounded, text


def value_portfolio(state, marks, fx, *, as_of, max_age_seconds=86400):
    if not isinstance(state, dict):
        raise ValueError("valuation requires a journal state")
    spec = AccountSpec.compile(state.get("account"))
    when = timestamp(as_of)
    if type(max_age_seconds) is not int or not 0 <= max_age_seconds <= 366 * 86400:
        raise ValueError("max mark age must be a nonnegative integer up to 366 days")
    if state.get("latest_timestamp") and timestamp(state["latest_timestamp"]) > when:
        raise ValueError(
            "current ledger contains events after the valuation time; historical state replay is required"
        )
    if not isinstance(marks, dict) or not isinstance(fx, dict):
        raise ValueError("marks and FX must be objects")
    if len(marks) > 1000 or len(fx) > 32:
        raise ValueError("valuation input exceeds instrument or currency budget")
    parsed_marks, parsed_fx = {}, {}
    for name, quote in marks.items():
        spec.instrument(name)
        if not isinstance(quote, dict) or set(quote) != {"price", "timestamp"}:
            raise ValueError("mark requires exactly price and timestamp")
        price = decimal_value(quote["price"], "mark price", nonnegative=True)
        observed = timestamp(quote["timestamp"])
        if observed > when:
            raise ValueError("mark timestamp lies after valuation time")
        parsed_marks[name] = (price, (when - observed).total_seconds())
    for currency, quote in fx.items():
        spec.places(currency)
        if not isinstance(quote, dict) or set(quote) != {"rate", "timestamp"}:
            raise ValueError("FX quote requires exactly rate and timestamp")
        rate = decimal_value(quote["rate"], "FX valuation rate", positive=True)
        if currency == spec.base_currency and rate != 1:
            raise ValueError("base-currency FX rate must equal one")
        observed = timestamp(quote["timestamp"])
        if observed > when:
            raise ValueError("FX timestamp lies after valuation time")
        parsed_fx[currency] = (rate, (when - observed).total_seconds())
    base_places = spec.places(spec.base_currency)
    missing, warnings = [], []

    def rate_for(currency):
        if currency == spec.base_currency:
            return Decimal(1)
        quote = parsed_fx.get(currency)
        if quote is None:
            missing.append({"kind": "fx", "currency": currency, "reason": "missing"})
            return None
        if quote[1] > max_age_seconds:
            missing.append({"kind": "fx", "currency": currency, "reason": "stale"})
            return None
        return quote[0]

    cash_rows, position_rows = [], []
    receivables = dividend_assets(state, spec)
    receivable_rows = []
    with arithmetic():
        known = ZERO
        for currency, amount in sorted(state["cash"].items()):
            spec.places(currency)
            value = decimal_value(amount, "cash balance", nonnegative=True)
            rate = rate_for(currency) if value else Decimal(1)
            converted = rounded(value * rate, base_places) if rate is not None else None
            if converted is not None:
                known += converted
            cash_rows.append(
                {
                    "currency": currency,
                    "amount": text(value),
                    "base_value": text(converted) if converted is not None else None,
                }
            )
        for label, item in sorted(receivables.items()):
            currency = item["currency"]
            amount = Decimal(item["amount"])
            rate = rate_for(currency)
            converted = (
                rounded(amount * rate, base_places) if rate is not None else None
            )
            if converted is not None:
                known += converted
            receivable_rows.append(
                {
                    "accrual_id": label,
                    "currency": currency,
                    "amount": item["amount"],
                    "base_value": text(converted) if converted is not None else None,
                }
            )
        for name, position in sorted(state["positions"].items()):
            instrument = spec.instrument(name)
            quantity = decimal_value(
                position["quantity"], "position quantity", positive=True
            )
            basis = decimal_value(position["basis"], "position basis", nonnegative=True)
            quote = parsed_marks.get(name)
            mark = None
            if quote is None:
                missing.append(
                    {"kind": "mark", "instrument": name, "reason": "missing"}
                )
            elif quote[1] > max_age_seconds:
                missing.append({"kind": "mark", "instrument": name, "reason": "stale"})
            else:
                mark = quote[0]
            rate = rate_for(instrument.quote_currency)
            value = (
                rounded(quantity * mark, spec.places(instrument.quote_currency))
                if mark is not None
                else None
            )
            converted = (
                rounded(value * rate, base_places)
                if value is not None and rate is not None
                else None
            )
            if converted is not None:
                known += converted
            position_rows.append(
                {
                    "instrument": name,
                    "symbol": instrument.symbol,
                    "venue": instrument.venue,
                    "quantity": text(quantity),
                    "quote_currency": instrument.quote_currency,
                    "basis": text(basis),
                    "mark": text(mark) if mark is not None else None,
                    "market_value": text(value) if value is not None else None,
                    "unrealized_quote_pnl": (
                        text(value - basis) if value is not None else None
                    ),
                    "base_value": text(converted) if converted is not None else None,
                }
            )
        # De-duplicate missing FX entries when cash and several instruments share it.
        missing = [
            dict(items)
            for items in dict.fromkeys(tuple(sorted(item.items())) for item in missing)
        ]
        complete = not missing
        equity = rounded(known, base_places) if complete else None
        for position in position_rows:
            value = position["base_value"]
            position["weight_percent"] = (
                text((Decimal(value) / equity * 100).quantize(Decimal("0.000001")))
                if equity is not None and equity > 0 and value is not None
                else None
            )
        for instrument in spec.instruments:
            if (
                instrument.active_until is not None
                and when >= instrument.active_until
                and instrument.id in state["positions"]
            ):
                warnings.append(
                    {"code": "held_after_active_interval", "instrument": instrument.id}
                )
    result = {
        "complete": complete,
        "sequence": state["last_sequence"],
        "as_of": timestamp_text(when),
        "base_currency": spec.base_currency,
        "equity": text(equity) if equity is not None else None,
        "known_base_value": text(rounded(known, base_places)),
        "cash": cash_rows,
        "positions": position_rows,
        "missing_inputs": missing,
        "warnings": warnings,
        "max_age_seconds": max_age_seconds,
        "fx_direction": "base currency units per one quote currency unit",
        "rounding_policy": "half-even at each cash/position conversion to base currency",
        "scope": "current long-only settled-cash journal valuation; no FX profit attribution or tax reporting",
    }

    if any(
        name.startswith("dividend_receivable:")
        for accounts in state.get("accounts", {}).values()
        for name in accounts
    ):
        result["dividend_receivables"] = receivable_rows
        result["scope"] = (
            "long-only journal valuation including accrued net dividend assets; no tax reporting"
        )
        result["rounding_policy"] = (
            "half-even per cash, position and dividend-asset conversion to base currency"
        )
    return result
