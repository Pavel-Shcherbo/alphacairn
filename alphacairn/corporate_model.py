"""Explicit unadjusted-price corporate actions with bounded, declared clocks."""

from .instruments import identity, timestamp, timestamp_text
from .money import arithmetic, decimal_value, text


def compile_actions(value, account, start, end, bars):
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError("execution supports at most 200 corporate actions")
    if len(value) * len(bars) > 1000000:
        raise ValueError("corporate action/bar coverage exceeds one million checks")
    output = []
    ids = set()
    splits = set()
    with arithmetic():
        for item in value:
            if not isinstance(item, dict) or item.get("kind") not in (
                "split",
                "cash_dividend",
            ):
                raise ValueError("corporate action requires split or cash_dividend")
            kind = item["kind"]
            required = {"kind", "id", "instrument", "known_at"} | (
                {"at", "numerator", "denominator", "order_policy"}
                if kind == "split"
                else {"ex_at", "pay_at", "amount_per_share", "withholding_bps"}
            )
            if set(item) != required:
                raise ValueError("corporate action fields do not match contract")
            label = identity(item["id"], "corporate action ID")
            if label in ids:
                raise ValueError("corporate action IDs must be unique")
            ids.add(label)
            instrument = account.instrument(item["instrument"])
            if instrument.kind != "equity":
                raise ValueError("corporate actions require an equity instrument")
            at = timestamp(item["at"] if kind == "split" else item["ex_at"])
            known = timestamp(item["known_at"])
            if known > at or at > end:
                raise ValueError(
                    "corporate action must be known by effectiveness and not follow execution end"
                )
            instrument.require_active(at)
            result = {
                "kind": kind,
                "id": label,
                "instrument": instrument.id,
                "known_at": timestamp_text(known),
            }
            if kind == "split":
                n, d = item["numerator"], item["denominator"]
                if (
                    type(n) is not int
                    or type(d) is not int
                    or not 1 <= n <= 1000000
                    or not 1 <= d <= 1000000
                    or n == d
                ):
                    raise ValueError(
                        "split requires distinct positive integer ratio terms up to one million"
                    )
                if item["order_policy"] not in ("cancel", "adjust"):
                    raise ValueError("split order policy must be cancel or adjust")
                key = (instrument.id, at)
                if key in splits:
                    raise ValueError(
                        "two splits for one instrument cannot share an instant"
                    )
                splits.add(key)
                result.update(
                    at=timestamp_text(at),
                    numerator=n,
                    denominator=d,
                    order_policy=item["order_policy"],
                )
            else:
                pay = timestamp(item["pay_at"])
                if at < start or pay < at:
                    raise ValueError("dividend requires execution start <= ex <= pay")
                amount = decimal_value(
                    item["amount_per_share"], "dividend per share", positive=True
                )
                withholding = decimal_value(
                    item["withholding_bps"], "withholding bps", nonnegative=True
                )
                if withholding > 10000:
                    raise ValueError("withholding cannot exceed 10,000 bps")
                result.update(
                    ex_at=timestamp_text(at),
                    pay_at=timestamp_text(pay),
                    amount_per_share=text(amount),
                    withholding_bps=text(withholding),
                )
            if any(
                bar["instrument"] == instrument.id
                and timestamp(bar["opened_at"]) < at < timestamp(bar["closed_at"])
                for bar in bars
            ):
                raise ValueError(
                    "split or dividend ex instant cannot fall inside a full-session bar"
                )
            output.append(result)
    return sorted(
        output,
        key=lambda item: (
            item.get("at", item.get("ex_at")),
            0 if item["kind"] == "split" else 1,
            item["id"],
        ),
    )


