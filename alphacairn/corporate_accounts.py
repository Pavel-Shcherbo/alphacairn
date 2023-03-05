"""Outstanding dividend assets derived from balanced journal posting accounts."""

from .money import exact_amount, text

PREFIX = "dividend_receivable:"


def dividend_assets(state, spec):
    result = {}
    for currency, accounts in state.get("accounts", {}).items():
        for name, value in accounts.items():
            if not name.startswith(PREFIX):
                continue
            amount = exact_amount(
                value, spec.places(currency), "dividend receivable", nonnegative=True
            )
            if amount:
                key = name[len(PREFIX) :]
                if key in result:
                    raise ValueError(
                        "one dividend receivable cannot use multiple currencies"
                    )
                result[key] = {"currency": currency, "amount": text(amount)}
    return result
