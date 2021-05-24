"""Deterministic long-only order book over explicit open and close phases."""

from decimal import Decimal

from .execution_money import affordable_quantity, execution_price, fill_cost, lots
from .money import ZERO, arithmetic, decimal_value, text

LIVE = frozenset({"open", "partially_filled"})


class ExecutionBook:
    def __init__(self, plan):
        self.plan = plan
        self.account = plan.account
        self.definition = plan.definition
        self.cash = {
            code: Decimal(value)
            for code, value in self.definition["initial_cash"].items()
        }
        self.positions = {}
        self.orders = {}
        self.events = []
        self.fills = []
        self.ledger_events = []
        self.bars = {}
        self.rate = Decimal(self.definition["fees"]["rate_bps"])
        self.minimum = {
            code: Decimal(value)
            for code, value in self.definition["fees"]["minimum"].items()
        }
        self.slip = Decimal(self.definition["slippage_bps"])
        for code, value in self.cash.items():
            if value:
                self.ledger_events.append(
                    {
                        "id": "simfund-" + code,
                        "timestamp": self.definition["starts_at"],
                        "kind": "deposit",
                        "currency": code,
                        "amount": text(value),
                    }
                )
        for sequence, command in enumerate(self.definition["commands"]):
            if command["action"] == "submit":
                self.orders[command["id"]] = {
                    "definition": command,
                    "sequence": sequence,
                    "status": "scheduled",
                    "remaining": Decimal(command["quantity"]),
                    "filled": ZERO,
                    "price_quantity": ZERO,
                    "fees": ZERO,
                    "attempts": 0,
                    "first_bar": None,
                    "last_block_reason": None,
                    "cancel_requested_at": None,
                    "completed_at": None,
                }
        for index, bar in enumerate(self.definition["bars"]):
            instrument = self.account.instrument(bar["instrument"])
            quantity = Decimal(bar["liquidity"])
            budget = lots(quantity, instrument.quantity_step) * instrument.quantity_step
            self.bars[index] = {
                "definition": bar,
                "initial": budget,
                "remaining": budget,
                "eligible": set(),
            }

    def emit(self, kind, at, **fields):
        if len(self.events) >= 20000:
            raise ValueError("execution trace exceeds 20,000 events")
        self.events.append(
            {"sequence": len(self.events) + 1, "kind": kind, "at": at, **fields}
        )

    def terminal(self, order, status, at, reason):
        order["status"] = status
        order["completed_at"] = at
        self.emit(
            status,
            at,
            order_id=order["definition"]["id"],
            reason=reason,
            remaining=text(order["remaining"]),
        )

    def command(self, command):
        if command["action"] == "submit":
            order = self.orders[command["id"]]
            order["status"] = "open"
            self.emit("submitted", command["at"], order_id=command["id"])
        else:
            order = self.orders[command["order_id"]]
            if order["status"] in LIVE:
                if order["cancel_requested_at"] is None:
                    order["cancel_requested_at"] = command["at"]
                self.emit(
                    "cancel_requested",
                    command["at"],
                    order_id=command["order_id"],
                    command_id=command["id"],
                )
            else:
                self.emit(
                    "cancel_ignored",
                    command["at"],
                    order_id=command["order_id"],
                    command_id=command["id"],
                    status=order["status"],
                )

    def expire(self, order_id, at):
        order = self.orders[order_id]
        if order["status"] in LIVE:
            self.terminal(order, "expired", at, "explicit_expiry_or_instrument_end")

    def priority(self, order):
        return order["definition"]["at"], order["sequence"]

