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

