"""Exact fill cost, quantity affordability and last-known multi-currency marks."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .instruments import timestamp
from .money import ZERO, arithmetic, decimal_value, rounded, text


def lots(quantity, step):
    return int((quantity / step).to_integral_value(rounding=ROUND_FLOOR))


def execution_price(instrument, opening, side, slippage_bps, limit=None):
    with arithmetic():
        raw = (
            opening * (1 + slippage_bps / 10000)
            if side == "buy"
            else opening * (1 - slippage_bps / 10000)
        )
        rounding = ROUND_CEILING if side == "buy" else ROUND_FLOOR
        price = (raw / instrument.price_tick).to_integral_value(
            rounding=rounding
        ) * instrument.price_tick
        if limit is not None:
            price = min(price, limit) if side == "buy" else max(price, limit)
        return decimal_value(price, "execution price", nonnegative=True)


def fill_cost(quantity, price, places, rate_bps, minimum):
    notional = rounded(quantity * price, places)
    fee = (
        max(rounded(notional * rate_bps / 10000, places), minimum) if quantity else ZERO
    )
    return notional, fee


def affordable_quantity(
    instrument, maximum, price, side, cash, position, places, rate_bps, minimum
):
    with arithmetic():
        count = lots(maximum, instrument.quantity_step)
        if side == "sell":
            count = min(count, lots(position, instrument.quantity_step))
            quantity = count * instrument.quantity_step
            notional, fee = fill_cost(quantity, price, places, rate_bps, minimum)
            return quantity if notional > 0 and cash + notional >= fee else ZERO
        low, high = 0, count
        while low < high:
            middle = (low + high + 1) // 2
            notional, fee = fill_cost(
                middle * instrument.quantity_step, price, places, rate_bps, minimum
            )
            if notional + fee <= cash:
                low = middle
            else:
                high = middle - 1
        quantity = low * instrument.quantity_step
        notional, _ = fill_cost(quantity, price, places, rate_bps, minimum)
        return quantity if notional > 0 else ZERO


def marked_value(account, cash, positions, marks, fx, *, at, max_age, receivables=None):
    when = timestamp(at)
    base_places = account.places(account.base_currency)
    totals = {}
    missing = []
    with arithmetic():
        components = []
        required_fx = {
            code
            for code, value in cash.items()
            if value and code != account.base_currency
        }
        for code, value in cash.items():
            totals[code] = value
            components.append((code, value))
        for receivable in (receivables or {}).values():
            currency = receivable["currency"]
            account.places(currency)
            amount = decimal_value(
                receivable["amount"], "dividend receivable", nonnegative=True
            )
            if amount:
                totals[currency] = totals.get(currency, ZERO) + amount
                components.append((currency, amount))
                if currency != account.base_currency:
                    required_fx.add(currency)
        for name, quantity in positions.items():
            if not quantity:
                continue
            instrument = account.instrument(name)
            if instrument.quote_currency != account.base_currency:
                required_fx.add(instrument.quote_currency)
            quote = marks.get(name)
            if (
                quote is None
                or (when - timestamp(quote["at"])).total_seconds() > max_age
            ):
                missing.append(
                    {
                        "kind": "mark",
                        "instrument": name,
                        "reason": "missing" if quote is None else "stale",
                    }
                )
                continue
            value = rounded(
                quantity * Decimal(quote["price"]),
                account.places(instrument.quote_currency),
            )
            totals[instrument.quote_currency] = (
                totals.get(instrument.quote_currency, ZERO) + value
            )
            components.append((instrument.quote_currency, value))
        known = ZERO
        rates = {account.base_currency: Decimal(1)}
        for currency in sorted(required_fx):
            quote = fx.get(currency)
            if (
                quote is None
                or (when - timestamp(quote["at"])).total_seconds() > max_age
            ):
                missing.append(
                    {
                        "kind": "fx",
                        "currency": currency,
                        "reason": "missing" if quote is None else "stale",
                    }
                )
            else:
                rates[currency] = Decimal(quote["rate"])
        for currency, value in components:
            if value and currency in rates:
                known += rounded(value * rates[currency], base_places)
        known = rounded(known, base_places)
    return {
        "at": at,
        "complete": not missing,
        "equity": text(known) if not missing else None,
        "known_base_value": text(known),
        "quote_currency_values": {
            code: text(value) for code, value in sorted(totals.items())
        },
        "quote_values_partial": any(item["kind"] == "mark" for item in missing),
        "missing_count": len(missing),
        "missing_sample": missing[:20],
        "missing_diagnostics_complete": len(missing) <= 20,
    }
