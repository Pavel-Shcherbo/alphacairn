"""Daily-bar simulator: previous-close signals, next-open execution."""

import csv
import math
import hashlib
import json
from collections import deque
from datetime import date


def parse_bars(stream):
    rows = list(csv.DictReader(stream))
    bars, previous = [], None
    for row in rows:
        day = date.fromisoformat(row["date"])
        opening, close = float(row["open"]), float(row["close"])
        if previous is not None and day <= previous:
            raise ValueError("bar dates must be strictly increasing")
        if not all(math.isfinite(x) and x > 0 for x in [opening, close]):
            raise ValueError("prices must be positive and finite")
        bars.append({"date": day.isoformat(), "open": opening, "close": close})
        previous = day
    if len(bars) < 2:
        raise ValueError("at least two bars are required")
    return bars


def load_bars(path):
    with open(path, newline="") as stream:
        return parse_bars(stream)


def dataset_digest(bars):
    normalized = [
        {
            "date": date.fromisoformat(row["date"]).isoformat(),
            "open": float(row["open"]),
            "close": float(row["close"]),
        }
        for row in bars
    ]
    payload = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def simulate(
    bars,
    lookback=3,
    initial_cash=10000,
    fee_bps=10,
    slippage_bps=5,
    buy_and_hold=False,
    trade_from=0,
    liquidate_at_end=False,
):
    if type(lookback) is not int or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial cash must be positive and finite")
    if not all(math.isfinite(x) and 0 <= x < 10000 for x in [fee_bps, slippage_bps]):
        raise ValueError("cost rates must be finite and between 0 and 10000 bps")
    if not bars:
        raise ValueError("bars must not be empty")
    if type(trade_from) is not int or not 0 <= trade_from < len(bars):
        raise ValueError("trade_from must identify an existing bar")
    if type(liquidate_at_end) is not bool:
        raise ValueError("liquidate_at_end must be boolean")
    previous = None
    for bar in bars:
        day = date.fromisoformat(bar["date"])
        if previous is not None and day <= previous:
            raise ValueError("bar dates must be strictly increasing")
        if not all(
            math.isfinite(bar[key]) and bar[key] > 0 for key in ["open", "close"]
        ):
            raise ValueError("prices must be positive and finite")
        previous = day
    cash, shares, peak, drawdown = float(initial_cash), 0.0, float(initial_cash), 0.0
    history, trades = [], []
    closes = deque()
    rolling_total = 0.0
    fee_rate, slip = fee_bps / 10000, slippage_bps / 10000
    for index, bar in enumerate(bars):
        opening, close = bar["open"], bar["close"]
        target = index >= trade_from and (
            buy_and_hold
            or (len(closes) == lookback and closes[-1] > rolling_total / lookback)
        )
        if target and shares == 0:
            execution = opening * (1 + slip)
            shares = cash / (execution * (1 + fee_rate))
            notional = shares * execution
            fee = notional * fee_rate
            cash = 0.0
            trades.append(
                {
                    "date": bar["date"],
                    "side": "buy",
                    "quantity": shares,
                    "price": execution,
                    "fee": fee,
                    "reason": "signal",
                    "signal_date": bars[index - 1]["date"] if index else None,
                    "execution_point": "open",
                }
            )
        elif not target and shares > 0:
            execution = opening * (1 - slip)
            notional = shares * execution
            fee = notional * fee_rate
            cash += notional - fee
            trades.append(
                {
                    "date": bar["date"],
                    "side": "sell",
                    "quantity": shares,
                    "price": execution,
                    "fee": fee,
                    "reason": "signal",
                    "signal_date": bars[index - 1]["date"] if index else None,
                    "execution_point": "open",
                }
            )
            shares = 0.0
        invested = shares > 0
        if liquidate_at_end and index == len(bars) - 1 and shares > 0:
            execution = close * (1 - slip)
            notional = shares * execution
            fee = notional * fee_rate
            cash += notional - fee
            trades.append(
                {
                    "date": bar["date"],
                    "side": "sell",
                    "quantity": shares,
                    "price": execution,
                    "fee": fee,
                    "reason": "scheduled_window_exit",
                    "signal_date": None,
                    "execution_point": "close",
                }
            )
            shares = 0.0
        equity = cash + shares * close
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError(
                "portfolio arithmetic exceeded the supported positive finite range"
            )
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        history.append(
            {
                "date": bar["date"],
                "equity": equity,
                "target": int(target),
                "cash": cash,
                "quantity": shares,
                "position_value": shares * close,
                "invested_during_bar": invested,
            }
        )
        removed = closes.popleft() if len(closes) == lookback else 0.0
        try:
            rolling_total = math.fsum([rolling_total, close, -removed])
        except OverflowError as error:
            raise ValueError(
                "rolling price sum exceeds the supported numeric range"
            ) from error
        closes.append(close)
    return {
        "initial_cash": initial_cash,
        "final_equity": history[-1]["equity"],
        "total_return": history[-1]["equity"] / initial_cash - 1,
        "max_drawdown": drawdown,
        "fees": sum(trade["fee"] for trade in trades),
        "trade_count": len(trades),
        "trades": trades,
        "equity": history,
        "assumptions": "Long-only fractional shares; signal at previous close; next-open execution; fixed costs; "
        + (
            "scheduled final-close liquidation with costs."
            if liquidate_at_end
            else "final position marked, not liquidated."
        ),
    }
