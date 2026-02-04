"""Plan state-aware target-inventory orders, then replay through the journal engine."""

import copy
from decimal import Decimal

from .corporate_book import CorporateBook
from .execution_book import ExecutionBook, LIVE
from .execution_clock import timeline_groups
from .execution_engine import simulate_execution
from .execution_model import compile_execution
from .instruments import timestamp, timestamp_text
from .market_model import canonical, digest
from .money import ZERO, arithmetic, text
from .strategy_inputs import prepare_strategy_inputs

ASSUMPTIONS = [
    "Signals use each decision's own historical universe and bar-vintage snapshots, gated by the explicitly selected publication or recording clock.",
    "Long-only target inventory is the declared fixed quantity when the last eligible close is strictly above its trailing mean, otherwise zero; this is a reproducible control strategy, not a return claim.",
    "Missing or stale features use the explicit hold/exit policy. Leaving the historical universe targets zero; inactive instruments remain visible and cannot receive a fabricated liquidation.",
    "Decisions observe actual prior fills and settled quote-currency cash. Market IOC orders are submitted for the remaining inventory difference; costs and liquidity can prevent target attainment.",
    "An existing live order defers a new order for that instrument until a later decision; a changed signal does not retroactively cancel a pending first-open execution.",
    "At a shared instant expiry and closes precede decisions, and decisions precede opens. Submission is never eligible for an open at the identical timestamp.",
    "The declared allocation order breaks ties among same-decision submissions; older pending orders retain submission-time priority. Simultaneous sells do not pre-fund earlier buys unless that ordering permits it.",
    "Execution prices are a separate declared realization vintage and are never supplied to the signal calculator. Raw-price corporate actions and market/settlement calendars are not inferred.",
    "Snapshot hashes prove portable content integrity, not source authenticity, market-data licensing or completeness of an external provider's history.",
]


def _cancelled(callback):
    if callback and callback():
        raise ValueError("strategy cancelled; no complete report was produced")


def simulate_strategy(inputs, *, should_cancel=None):
    if should_cancel is not None and not callable(should_cancel):
        raise ValueError("strategy cancellation must be callable")
    _cancelled(should_cancel)
    prepared = prepare_strategy_inputs(inputs)
    with arithmetic():
        return _simulate(prepared, should_cancel)


def _simulate(prepared, should_cancel):
    config, plan = prepared.configuration, prepared.execution
    book = ExecutionBook(plan)
    corporate = CorporateBook(book)
    commands, decisions = [], []
    extras = [
        (window["decision"]["at"], "decision", index)
        for index, window in enumerate(prepared.windows)
    ]
    for instrument in plan.account.instruments:
        if instrument.active_until is not None:
            when = timestamp_text(instrument.active_until)
            if plan.definition["starts_at"] <= when <= plan.definition["ends_at"]:
                extras.append((when, "instrument_end", instrument.id))
    evaluations = 0
    for at, groups in timeline_groups(plan.definition, extras):
        _cancelled(should_cancel)
        book.settlements.process(at)
        if groups.get("instrument_end"):
            for order in book.orders.values():
                expiry = order["definition"]["expires_at"]
                if expiry is not None and expiry <= at:
                    book.expire(order["definition"]["id"], at)
        if groups.get("close"):
            book.close_bars(at, groups["close"])
        corporate.process(at, groups)
        for index in groups.get("decision", []):
            window = prepared.windows[index]
            features = {item["instrument"]: item for item in window["features"]}
            decision = {
                "index": index + 1,
                "at": at,
                "session": window["decision"]["session"],
                "membership_sha256": window["membership_sha256"],
                "cash_before": {code: text(value) for code, value in book.cash.items()},
                "positions_before": {
                    name: text(value) for name, value in book.positions.items() if value
                },
                "actions": [],
            }
            for name in config["allocation_order"]:
                instrument = plan.account.instrument(name)
                current = book.positions.get(name, ZERO)
                feature = features.get(name)
                reason = "outside_universe" if feature is None else feature["reason"]
                target = ZERO
                if feature is not None and feature["ready"]:
                    target = (
                        Decimal(config["target_quantities"][name])
                        if feature["above_mean"]
                        else ZERO
                    )
                    reason = (
                        "above_mean" if feature["above_mean"] else "at_or_below_mean"
                    )
                elif feature is not None and config["missing_signal_policy"] == "hold":
                    target = current
                pending = [
                    order["definition"]["id"]
                    for order in book.orders.values()
                    if order["definition"]["instrument"] == name
                    and order["status"] in LIVE
                ]
                action = {
                    "instrument": name,
                    "signal_reason": reason,
                    "feature_snapshot_sha256": (
                        feature["snapshot_sha256"] if feature else None
                    ),
                    "current_quantity": text(current),
                    "target_quantity": text(target),
                    "delta_quantity": text(target - current),
                    "pending_orders": pending,
                    "outcome": "at_target",
                    "order_id": None,
                }
                try:
                    instrument.require_active(timestamp(at))
                except ValueError:
                    action["outcome"] = "inactive_instrument"
                else:
                    if pending:
                        action["outcome"] = "waiting_for_pending_order"
                    elif (
                        feature is not None
                        and not feature["ready"]
                        and config["missing_signal_policy"] == "hold"
                    ):
                        action["outcome"] = "missing_signal_hold"
                    elif target != current:
                        if len(commands) >= 1000:
                            raise ValueError(
                                "strategy exceeds 1,000 orders; partition the study"
                            )
                        evaluations += sum(
                            bar["instrument"] == name for bar in plan.definition["bars"]
                        )
                        if evaluations > 2_000_000:
                            raise ValueError(
                                "strategy exceeds two million order/bar evaluations"
                            )
                        command = {
                            "action": "submit",
                            "id": "decision-"
                            + str(index + 1)
                            + "-order-"
                            + str(len(commands) + 1),
                            "at": at,
                            "instrument": name,
                            "side": "buy" if target > current else "sell",
                            "kind": "market",
                            "quantity": text(abs(target - current)),
                            "limit": None,
                            "time_in_force": "IOC",
                            "expires_at": (
                                timestamp_text(instrument.active_until)
                                if instrument.active_until is not None
                                else None
                            ),
                        }
                        book._register_submission(command, len(commands))
                        book.command(command)
                        commands.append(command)
                        action.update(outcome="order_submitted", order_id=command["id"])
                decision["actions"].append(action)
            decisions.append(decision)
        if groups.get("open"):
            book.open_bars(at, groups["open"])
    _cancelled(should_cancel)
    scenario = compile_execution({**plan.definition, "commands": commands})
    execution = simulate_execution(scenario, should_cancel=should_cancel)
    # A separate chronological pass must reproduce the planning pass exactly.
    if (
        execution["fills"] != book.fills
        or execution["orders"] != book.order_reports()
        or execution["events"] != book.events
        or execution["ledger_events"] != book.ledger_events
        or execution["liquidity"] != book.bar_reports()
        or any(
            Decimal(execution.get("available_cash", execution["cash"])[code]) != value
            for code, value in book.cash.items()
        )
    ):
        raise RuntimeError("strategy planning differs from full execution replay")
    if plan.definition["version"] in (3, 4, 5) and (
        execution["corporate_actions"] != corporate.reports
        or execution["dividend_receivables"] != corporate.outstanding()
    ):
        raise RuntimeError(
            "strategy corporate actions differ from full execution replay"
        )
    if (
        book.settlements.enabled
        and execution["settlement"] != book.settlements.summary()
    ):
        raise RuntimeError("strategy settlement decisions differ from execution replay")
    own_positions = {name: value for name, value in book.positions.items() if value}
    replay_positions = {
        name: Decimal(value["quantity"])
        for name, value in execution["positions"].items()
    }
    if own_positions != replay_positions:
        raise RuntimeError("strategy positions differ from replayed journal")
    result = {
        "format": "alphacairn.strategy-report.v1",
        "inputs_sha256": prepared.sha256,
        "configuration_sha256": digest(config),
        "completed": True,
        "planning_replayed": True,
        "signal": "close_strictly_above_trailing_mean",
        "windows": copy.deepcopy(prepared.windows),
        "decisions": decisions,
        "scenario": scenario.definition,
        "execution": execution,
        "assumptions": list(ASSUMPTIONS),
    }
    if len(canonical(result)) > 32 * 1024 * 1024:
        raise ValueError("strategy report exceeds 32 MiB; partition the study")
    result["sha256"] = digest(result)
    return result
