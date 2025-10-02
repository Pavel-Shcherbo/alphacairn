"""Deterministic long-only order book over explicit open and close phases."""

from decimal import Decimal
import copy

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
        from .opening_positions import seed_opening

        seed_opening(self)
        from .settlement_book import SettlementBook

        self.settlements = SettlementBook(self)
        for sequence, command in enumerate(self.definition["commands"]):
            if command["action"] == "submit":
                self._register_submission(command, sequence)
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

    def _register_submission(self, command, sequence):
        """Install a normalized submission before activation by a trusted planner."""
        if self.definition["version"] in (3, 4, 5):
            command = copy.deepcopy(command)
        if command["id"] in self.orders:
            raise ValueError("duplicate execution-book order ID")
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

        if self.definition["version"] in (3, 4, 5):
            self.orders[command["id"]]["original_definition"] = copy.deepcopy(command)
            self.orders[command["id"]]["corporate_adjustments"] = []

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

    def _fill(self, order, bar, at, phase, price):
        definition = order["definition"]
        instrument = self.account.instrument(definition["instrument"])
        currency = instrument.quote_currency
        order["attempts"] += 1
        if price <= 0:
            order["last_block_reason"] = "nonpositive_execution_price"
            return
        maximum = min(order["remaining"], bar["remaining"])
        position = self.positions.get(instrument.id, ZERO)
        if maximum < instrument.quantity_step:
            order["last_block_reason"] = "liquidity_or_quantity_step"
            return
        if definition["side"] == "sell" and position < instrument.quantity_step:
            order["last_block_reason"] = "insufficient_position"
            return
        quantity = affordable_quantity(
            instrument,
            maximum,
            price,
            definition["side"],
            self.cash[currency],
            position,
            self.account.places(currency),
            self.rate,
            self.minimum[currency],
        )
        if not quantity:
            order["last_block_reason"] = "insufficient_cash_fee_or_positive_notional"
            return
        notional, fee = fill_cost(
            quantity,
            price,
            self.account.places(currency),
            self.rate,
            self.minimum[currency],
        )
        if len(self.ledger_events) >= 10000:
            raise ValueError("execution exceeds 10,000 funding/fill journal events")
        fill_id = "simfill-" + str(len(self.fills) + 1).zfill(6)
        settlement = None
        if self.settlements.enabled:
            settlement = self.settlements.fill(
                fill_id,
                instrument,
                definition["side"],
                quantity,
                price,
                notional,
                fee,
                at,
                bar["definition"]["session"],
            )
        sign = 1 if definition["side"] == "buy" else -1
        self.cash[currency] = (
            self.cash[currency]
            if self.settlements.enabled
            else decimal_value(
                (
                    self.cash[currency] - notional - fee
                    if sign == 1
                    else self.cash[currency] + notional - fee
                ),
                "cash after fill",
                nonnegative=True,
            )
        )
        self.positions[instrument.id] = decimal_value(
            position + sign * quantity, "position after fill", nonnegative=True
        )
        bar["remaining"] -= quantity
        order["remaining"] -= quantity
        order["filled"] += quantity
        order["price_quantity"] += quantity * price
        order["fees"] += fee
        order["last_block_reason"] = None
        fill = {
            "id": fill_id,
            "order_id": definition["id"],
            "instrument": instrument.id,
            "side": definition["side"],
            "at": at,
            "phase": phase,
            "session": bar["definition"]["session"],
            "quantity": text(quantity),
            "price": text(price),
            "notional": text(notional),
            "fee": text(fee),
            "currency": currency,
            "cash_after": text(self.cash[currency]),
            "position_after": text(self.positions[instrument.id]),
        }
        if settlement is not None:
            fill.update(
                settles_at=settlement["settles_at"],
                settlement_date=settlement["settlement_date"],
                cash_after=text(self.settlements.settled_cash[currency]),
                available_cash_after=text(self.cash[currency]),
                reserved_cash_after=text(
                    self.settlements.settled_cash[currency] - self.cash[currency]
                ),
            )
        self.fills.append(fill)
        if not self.settlements.enabled:
            self.ledger_events.append(
                {
                    "id": fill_id,
                    "timestamp": at,
                    "kind": "trade",
                    "instrument": instrument.id,
                    "side": definition["side"],
                    "quantity": text(quantity),
                    "price": text(price),
                    "fee": text(fee),
                }
            )
        self.emit("fill", at, order_id=definition["id"], fill_id=fill_id)
        if order["remaining"] == 0:
            self.terminal(order, "filled", at, "quantity_executed")
        else:
            order["status"] = "partially_filled"

    def open_bars(self, at, indices):
        opening = {
            self.bars[index]["definition"]["instrument"]: index for index in indices
        }
        candidates = sorted(
            (
                order
                for order in self.orders.values()
                if order["status"] in LIVE
                and order["definition"]["instrument"] in opening
                and order["definition"]["at"] < at
            ),
            key=self.priority,
        )
        with arithmetic():
            for order in candidates:
                definition = order["definition"]
                index = opening[definition["instrument"]]
                bar = self.bars[index]
                if (
                    order["cancel_requested_at"] is not None
                    and order["cancel_requested_at"] < at
                ):
                    self.terminal(
                        order,
                        "cancelled",
                        at,
                        "cancel_effective_at_next_instrument_open",
                    )
                    continue
                if order["first_bar"] is None:
                    order["first_bar"] = index
                bar["eligible"].add(definition["id"])
                opening_price = Decimal(bar["definition"]["open"])
                limit = (
                    Decimal(definition["limit"])
                    if definition["limit"] is not None
                    else None
                )
                marketable = (
                    limit is None
                    or definition["side"] == "buy"
                    and opening_price <= limit
                    or definition["side"] == "sell"
                    and opening_price >= limit
                )
                if marketable:
                    price = execution_price(
                        self.account.instrument(definition["instrument"]),
                        opening_price,
                        definition["side"],
                        self.slip,
                        limit,
                    )
                    self._fill(order, bar, at, "open", price)
                else:
                    order["last_block_reason"] = "limit_not_marketable_at_open"
                if definition["time_in_force"] == "IOC" and order["status"] in LIVE:
                    self.terminal(order, "cancelled", at, "IOC_remainder_after_open")

    def close_bars(self, at, indices):
        closing = {
            self.bars[index]["definition"]["instrument"]: index for index in indices
        }
        candidates = sorted(
            (
                order
                for order in self.orders.values()
                if order["status"] in LIVE
                and order["definition"]["instrument"] in closing
                and order["definition"]["id"]
                in self.bars[closing[order["definition"]["instrument"]]]["eligible"]
            ),
            key=self.priority,
        )
        with arithmetic():
            for order in candidates:
                definition = order["definition"]
                bar = self.bars[closing[definition["instrument"]]]
                if definition["kind"] == "limit" and (
                    definition["expires_at"] is None or definition["expires_at"] > at
                ):
                    limit = Decimal(definition["limit"])
                    touched = (
                        Decimal(bar["definition"]["low"]) <= limit
                        if definition["side"] == "buy"
                        else Decimal(bar["definition"]["high"]) >= limit
                    )
                    if touched:
                        self._fill(order, bar, at, "limit_touch_at_close", limit)
                    else:
                        order["last_block_reason"] = "limit_not_touched"
            for order in candidates:
                if (
                    order["status"] in LIVE
                    and order["definition"]["time_in_force"] == "DAY"
                ):
                    self.terminal(
                        order, "cancelled", at, "DAY_remainder_after_first_eligible_bar"
                    )

    def order_reports(self):
        result = []
        with arithmetic():
            for order in sorted(
                self.orders.values(), key=lambda item: item["sequence"]
            ):
                definition = order["definition"]
                result.append(
                    {
                        **definition,
                        "status": order["status"],
                        "remaining_quantity": text(order["remaining"]),
                        "filled_quantity": text(order["filled"]),
                        "average_fill_price": (
                            text(order["price_quantity"] / order["filled"])
                            if order["filled"]
                            else None
                        ),
                        "fees": text(order["fees"]),
                        "attempts": order["attempts"],
                        "last_block_reason": order["last_block_reason"],
                        "cancel_requested_at": order["cancel_requested_at"],
                        "completed_at": order["completed_at"],
                    }
                )
                if self.definition["version"] in (3, 4, 5):
                    result[-1]["original_definition"] = copy.deepcopy(
                        order["original_definition"]
                    )
                    result[-1]["corporate_adjustments"] = copy.deepcopy(
                        order["corporate_adjustments"]
                    )
        return result

    def bar_reports(self):
        return [
            {
                "instrument": item["definition"]["instrument"],
                "session": item["definition"]["session"],
                "liquidity_known_at": item["definition"]["liquidity_known_at"],
                "usable_liquidity": text(item["initial"]),
                "consumed": text(item["initial"] - item["remaining"]),
                "remaining": text(item["remaining"]),
            }
            for item in self.bars.values()
        ]
