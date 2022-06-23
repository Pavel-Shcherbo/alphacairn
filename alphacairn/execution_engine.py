"""Simulate bounded order scenarios and reconcile fills through the portfolio journal."""

import tempfile
from decimal import Decimal
from pathlib import Path

from .execution_book import ExecutionBook, LIVE
from .execution_clock import timeline_groups
from .execution_model import ExecutionPlan, compile_execution
from .execution_money import marked_value
from .ledger import Ledger
from .market_model import canonical, digest
from .money import ZERO, arithmetic, text
from .valuation import value_portfolio

ASSUMPTIONS = [
    "Long-only spot positions and settled cash per quote currency; no borrowing, shorting or automatic FX exchange.",
    "Orders become fill-eligible only at an instrument bar whose open is strictly later than submission.",
    "At a shared instant, explicit expiry precedes close fills; close processing precedes new commands and opens.",
    "Across instruments sharing an execution phase, submission time and input command order determine cash allocation.",
    "Market and marketable-limit fills use the open with adverse tick-rounded slippage; limits cap the execution price.",
    "Other limit touches are modeled at the limit on bar close, without asserting an observed intrabar path.",
    "Liquidity is a separately supplied pre-open known quantity budget shared by both sides and phases; it is not realized daily volume.",
    "IOC remainder cancels after its first eligible open; DAY remainder cancels after its first eligible bar closes; GTC remainder persists.",
    "Cancellation requests take effect at the next instrument open strictly after the request, including requests made during a bar.",
    "Each partial fill incurs its own percentage/minimum fee, rounded half-even in quote currency.",
    "Pending orders reserve neither cash nor shares; actual balances and positions are checked immediately before each fill.",
    "Positions are marked without forced final liquidation. Missing or stale marks/FX produce incomplete equity rather than zero.",
    "FX rates mean base currency units per one quote currency unit; each cash/position component converts with half-even rounding.",
    "Submitted commands, liquidity knowledge times and prices are caller-declared inputs, not authenticated historical evidence.",
]


def simulate_execution(definition, *, should_cancel=None):
    if should_cancel is not None and not callable(should_cancel):
        raise ValueError("execution cancellation must be callable")
    plan = (
        definition
        if isinstance(definition, ExecutionPlan)
        else compile_execution(definition)
    )
    if (
        digest(plan.definition) != plan.sha256
        or plan.account.definition() != plan.definition["account"]
    ):
        raise ValueError("compiled execution plan was mutated after validation")
    with arithmetic():
        return _simulate(plan, should_cancel)


def _simulate(plan, should_cancel):
    book = ExecutionBook(plan)
    scenario = plan.definition
    marks = {}
    fx = {}
    curve = []
    curve_bytes = 0
    for at, groups in timeline_groups(scenario):
        if should_cancel and should_cancel():
            raise ValueError("execution cancelled; no complete report was produced")
        for order_id in groups.get("expiry", []):
            book.expire(order_id, at)
        closes = groups.get("close", [])
        if closes:
            book.close_bars(at, closes)
            for index in closes:
                bar = scenario["bars"][index]
                marks[bar["instrument"]] = {"at": at, "price": bar["close"]}
        for index in groups.get("fx", []):
            quote = scenario["fx"][index]
            fx[quote["currency"]] = {"at": at, "rate": quote["rate"]}
        for index in sorted(groups.get("command", [])):
            book.command(scenario["commands"][index])
        if groups.get("open"):
            book.open_bars(at, groups["open"])
        if closes or at in (scenario["starts_at"], scenario["ends_at"]):
            point = marked_value(
                plan.account,
                book.cash,
                book.positions,
                marks,
                fx,
                at=at,
                max_age=scenario["max_mark_age_seconds"],
            )
            curve_bytes += len(canonical(point))
            if curve_bytes > 8 * 1024 * 1024:
                raise ValueError(
                    "execution equity curve exceeds 8 MiB; partition the study"
                )
            curve.append(point)
    if should_cancel and should_cancel():
        raise ValueError("execution cancelled before journal replay")
    # Replay is a separate implementation of cash/position accounting and FIFO basis.
    with tempfile.TemporaryDirectory(prefix="alphacairn-execution-") as directory:
        ledger = Ledger(Path(directory) / "fills.sqlite", plan.account.definition())
        if book.ledger_events:
            ledger.apply_batch(book.ledger_events)
        journal = ledger.state()
        for currency, value in book.cash.items():
            if Decimal(journal["cash"].get(currency, "0")) != value:
                raise RuntimeError("execution cash differs from replayed journal")
        own = {name: value for name, value in book.positions.items() if value}
        actual = {
            name: Decimal(position["quantity"])
            for name, position in journal["positions"].items()
        }
        if own != actual:
            raise RuntimeError("execution positions differ from replayed journal")
        replay = ledger.audit()
        if not replay["passed"]:
            raise RuntimeError("execution journal failed its independent replay audit")
        final_valuation = value_portfolio(
            journal,
            {
                key: {"price": value["price"], "timestamp": value["at"]}
                for key, value in marks.items()
            },
            {
                key: {"rate": value["rate"], "timestamp": value["at"]}
                for key, value in fx.items()
            },
            as_of=scenario["ends_at"],
            max_age_seconds=scenario["max_mark_age_seconds"],
        )
    if (
        final_valuation["complete"] != curve[-1]["complete"]
        or final_valuation["equity"] != curve[-1]["equity"]
        or final_valuation["known_base_value"] != curve[-1]["known_base_value"]
    ):
        raise RuntimeError("execution marked equity differs from journal valuation")
    if should_cancel and should_cancel():
        raise ValueError("execution cancelled during journal replay")
    order_reports = book.order_reports()
    statuses = {
        status: sum(order["status"] == status for order in order_reports)
        for status in ["open", "partially_filled", "filled", "cancelled", "expired"]
    }
    result = {
        "format": "alphacairn.execution-report.v1",
        "scenario_sha256": plan.sha256,
        "completed": True,
        "accounting_reconciled": True,
        "starts_at": scenario["starts_at"],
        "ends_at": scenario["ends_at"],
        "orders": order_reports,
        "order_counts": statuses,
        "open_order_count": sum(order["status"] in LIVE for order in order_reports),
        "fills": book.fills,
        "fees_by_currency": {
            code: text(
                sum(
                    (
                        Decimal(fill["fee"])
                        for fill in book.fills
                        if fill["currency"] == code
                    ),
                    ZERO,
                )
            )
            for code, _ in plan.account.currencies
        },
        "cash": {code: text(value) for code, value in book.cash.items()},
        "positions": journal["positions"],
        "liquidity": book.bar_reports(),
        "equity_curve": curve,
        "valuation": final_valuation,
        "events": book.events,
        "ledger_events": book.ledger_events,
        "ledger_state": journal,
        "ledger_audit": replay,
        "assumptions": list(ASSUMPTIONS),
    }
    if scenario["version"] == 2:
        from .session_calendar import validate_execution_calendar

        result["calendar_validation"] = validate_execution_calendar(
            scenario, plan.account
        )
    if len(canonical(result)) > 24 * 1024 * 1024:
        raise ValueError("execution report exceeds 24 MiB; partition the study")
    result["sha256"] = digest(result)
    return result
