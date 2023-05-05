"""Recheck dividend ownership from FIFO journal lots using rational money controls."""

from fractions import Fraction


def replay_actions(ledger, events, reports, actions):
    entitlements = {
        item["accrual_event_id"]: item
        for item in reports
        if item["kind"] == "cash_dividend" and item["accrual_event_id"] is not None
    }
    definitions = {item["id"]: item for item in actions}
    checks = []
    start = 0
    for index, event in enumerate(events):
        if event["kind"] != "dividend_accrual":
            continue
        if index > start:
            ledger.apply_batch(events[start:index])
        report = entitlements.get(event["id"])
        if report is None:
            raise RuntimeError("dividend journal accrual has no entitlement report")
        definition = definitions[report["id"]]
        state = ledger.state()
        quantity = Fraction(
            state["positions"].get(event["instrument"], {}).get("quantity", "0")
        )
        scale = 10 ** ledger.spec.places(
            ledger.spec.instrument(event["instrument"]).quote_currency
        )
        gross = round(quantity * Fraction(definition["amount_per_share"]) * scale)
        withholding = round(
            Fraction(gross) * Fraction(definition["withholding_bps"]) / 10000
        )
        if (
            quantity != Fraction(report["eligible_quantity"])
            or Fraction(event["gross"]) * scale != gross
            or Fraction(event["withholding"]) * scale != withholding
        ):
            raise RuntimeError(
                "dividend entitlement differs from independent journal ownership or rational rounding"
            )
        checks.append(
            {
                "action_id": report["id"],
                "accrual_event_id": event["id"],
                "journal_quantity": str(quantity),
                "gross_minor_units": gross,
                "withholding_minor_units": withholding,
                "passed": True,
            }
        )
        start = index
    if start < len(events):
        ledger.apply_batch(events[start:])
    return checks
