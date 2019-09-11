"""Select parameters on trailing data and evaluate subsequent disjoint windows."""

import math

from .analytics import compare, frequency, summarize
from .backtest import simulate


def walk_forward(
    bars,
    candidates,
    train_size=100,
    test_size=40,
    initial_cash=10000,
    fee_bps=10,
    slippage_bps=5,
    score="total_return",
    periods_per_year=365,
):
    frequency(periods_per_year)
    if not isinstance(candidates, list) or not candidates or len(candidates) > 100:
        raise ValueError("provide between 1 and 100 lookback candidates")
    if any(type(value) is not int or value < 1 for value in candidates):
        raise ValueError("lookback candidates must be positive integers")
    candidates = sorted(set(candidates))
    if type(train_size) is not int or train_size <= max(candidates):
        raise ValueError("training size must exceed every candidate lookback")
    if type(test_size) is not int or test_size < 1:
        raise ValueError("test_size must be a positive integer")
    if len(bars) <= train_size:
        raise ValueError(
            "data must include a training window and subsequent test observations"
        )
    window_count = math.ceil((len(bars) - train_size) / test_size)
    evaluated_bars = window_count * (
        train_size * len(candidates) + train_size + test_size
    )
    if evaluated_bars > 2_000_000:
        raise ValueError("candidate evaluation budget exceeded")
    if score not in {"total_return", "sharpe"}:
        raise ValueError("selection score must be total_return or sharpe")
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial cash must be positive and finite")
    cash = initial_cash
    windows, equity, trades = [], [], []
    costs = {"fee_bps": fee_bps, "slippage_bps": slippage_bps}
    for start in range(train_size, len(bars), test_size):
        end = min(start + test_size, len(bars))
        train = bars[start - train_size : start]
        scores = []
        for candidate in candidates:
            training = simulate(
                train,
                lookback=candidate,
                initial_cash=initial_cash,
                liquidate_at_end=True,
                **costs,
            )
            metrics = summarize(training["equity"], initial_cash, periods_per_year)
            scores.append({"lookback": candidate, "score": metrics[score]})
        eligible = [
            row
            for row in scores
            if row["score"] is not None and math.isfinite(row["score"])
        ]
        if not eligible:
            raise ValueError(
                "all training scores are undefined; choose a different metric or dataset"
            )
        selected = max(eligible, key=lambda row: (row["score"], -row["lookback"]))[
            "lookback"
        ]
        context = bars[start - train_size : end]
        evaluation = simulate(
            context,
            lookback=selected,
            initial_cash=cash,
            trade_from=train_size,
            liquidate_at_end=True,
            **costs,
        )
        observed = evaluation["equity"][train_size:]
        metrics = summarize(observed, cash, periods_per_year)
        windows.append(
            {
                "train_start": train[0]["date"],
                "train_end": train[-1]["date"],
                "test_start": observed[0]["date"],
                "test_end": observed[-1]["date"],
                "selected_lookback": selected,
                "training_scores": scores,
                "initial_cash": cash,
                "final_cash": evaluation["final_equity"],
                "fees": evaluation["fees"],
                "test_metrics": metrics,
            }
        )
        equity.extend(observed)
        trades.extend(evaluation["trades"])
        cash = evaluation["final_equity"]
    baseline = simulate(
        bars[train_size:],
        initial_cash=initial_cash,
        buy_and_hold=True,
        liquidate_at_end=True,
        **costs,
    )
    return {
        "parameters": {
            "candidates": candidates,
            "train_size": train_size,
            "test_size": test_size,
            "score": score,
            "periods_per_year": periods_per_year,
            **costs,
        },
        "windows": windows,
        "equity": equity,
        "trades": trades,
        "metrics": summarize(equity, initial_cash, periods_per_year),
        "baseline_metrics": summarize(
            baseline["equity"], initial_cash, periods_per_year
        ),
        "baseline": baseline,
        "comparison": (
            compare(equity, baseline["equity"], initial_cash, periods_per_year)
            if len(equity) >= 2
            else None
        ),
        "total_fees": sum(window["fees"] for window in windows),
        "training_trials": len(windows) * len(candidates),
        "evaluation_policy": "Parameters selected only on the preceding trailing window. Test windows are disjoint. Each test window starts in cash and has a prescheduled final-close liquidation with costs; cash carries into the next window. A final untouched holdout is not reserved by this function. No future-performance claim is made.",
    }
