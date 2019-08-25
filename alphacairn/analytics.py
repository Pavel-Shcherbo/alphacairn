"""Descriptive risk statistics under declared bar-frequency assumptions."""

import math
import random
import statistics
from collections import deque
from datetime import date


def finite(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def frequency(periods_per_year):
    if type(periods_per_year) is not int or not 1 <= periods_per_year <= 366:
        raise ValueError(
            "periods_per_year must be an integer between 1 and 366 for daily bars"
        )
    return periods_per_year


def quantile(values, probability):
    finite(probability, "probability")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between zero and one")
    if not values:
        raise ValueError("quantile requires observations")
    ordered = sorted(finite(value, "observation") for value in values)
    position = (len(ordered) - 1) * probability
    left = int(math.floor(position))
    right = int(math.ceil(position))
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def period_returns(equity, initial_cash):
    previous = finite(initial_cash, "initial_cash", positive=True)
    if not equity:
        raise ValueError("equity history must not be empty")
    result, previous_day = [], None
    for item in equity:
        day = date.fromisoformat(item["date"])
        if previous_day is not None and day <= previous_day:
            raise ValueError("equity dates must be strictly increasing")
        current = finite(item["equity"], "equity", positive=True)
        change = current / previous - 1
        if not math.isfinite(change) or change <= -1:
            raise ValueError("period return exceeds the supported finite range")
        result.append(change)
        previous, previous_day = current, day
    return result


def drawdown_history(equity, initial_cash):
    period_returns(equity, initial_cash)
    peak, peak_day = float(initial_cash), None
    current, episodes = None, []
    series, duration = [], 0
    for item in equity:
        value, day = item["equity"], item["date"]
        if value >= peak:
            if current is not None:
                current["recovery_date"] = day
                current["recovered"] = True
                episodes.append(current)
                current = None
            peak, peak_day, duration = value, day, 0
        else:
            duration += 1
            depth = 1 - value / peak
            if current is None:
                current = {
                    "peak_date": peak_day,
                    "first_underwater_date": day,
                    "trough_date": day,
                    "depth": depth,
                    "underwater_bars": 0,
                    "recovery_date": None,
                    "recovered": False,
                }
            current["underwater_bars"] += 1
            if depth > current["depth"]:
                current["depth"], current["trough_date"] = depth, day
        series.append(
            {"date": day, "drawdown": 1 - value / peak, "underwater_bars": duration}
        )
    if current is not None:
        episodes.append(current)
    return {
        "series": series,
        "episodes": episodes,
        "maximum": max(row["drawdown"] for row in series),
        "longest_underwater_bars": max(row["underwater_bars"] for row in series),
    }


def summarize(
    equity,
    initial_cash,
    periods_per_year=365,
    risk_free_annual=0.0,
    tail_probability=0.05,
):
    frequency(periods_per_year)
    finite(risk_free_annual, "risk_free_annual")
    if risk_free_annual <= -1:
        raise ValueError("annual risk-free rate must exceed -1")
    finite(tail_probability, "tail_probability")
    if not 0 < tail_probability < 1:
        raise ValueError("tail_probability must be between zero and one")
    changes = period_returns(equity, initial_cash)
    mean = statistics.fmean(changes)
    deviation = statistics.stdev(changes) if len(changes) >= 2 else None
    risk_free_period = math.expm1(math.log1p(risk_free_annual) / periods_per_year)
    excess = [change - risk_free_period for change in changes]
    downside = math.sqrt(statistics.fmean(min(change, 0) ** 2 for change in excess))
    threshold = quantile(changes, tail_probability)
    tail = [change for change in changes if change <= threshold]
    drawdowns = drawdown_history(equity, initial_cash)
    try:
        annualized = math.expm1(
            math.log(equity[-1]["equity"] / initial_cash)
            * periods_per_year
            / len(changes)
        )
    except OverflowError as error:
        raise ValueError("annualization exceeds the supported numeric range") from error
    return {
        "observations": len(changes),
        "periods_per_year": periods_per_year,
        "total_return": equity[-1]["equity"] / initial_cash - 1,
        "annualized_compound_return": annualized,
        "annualized_volatility": (
            deviation * math.sqrt(periods_per_year) if deviation is not None else None
        ),
        "sharpe": (
            statistics.fmean(excess) * math.sqrt(periods_per_year) / deviation
            if deviation is not None and deviation > 0
            else None
        ),
        "sortino": (
            statistics.fmean(excess) * math.sqrt(periods_per_year) / downside
            if downside > 0
            else None
        ),
        "maximum_drawdown": drawdowns["maximum"],
        "longest_underwater_bars": drawdowns["longest_underwater_bars"],
        "historical_var_loss": -threshold,
        "historical_expected_shortfall_loss": -statistics.fmean(tail),
        "tail_probability": tail_probability,
        "positive_bar_fraction": sum(change > 0 for change in changes) / len(changes),
        "risk_free_annual": risk_free_annual,
        "assumptions": "Bar-frequency annualization; sample standard deviation; empirical linear-interpolated tail quantile. Historical loss measures can be negative when all observations are gains. Ratios with zero denominator are undefined, not infinite. These are descriptive statistics, not risk forecasts.",
    }


def compare(
    strategy_equity,
    baseline_equity,
    initial_cash,
    periods_per_year=365,
    risk_free_annual=0,
):
    frequency(periods_per_year)
    if [row["date"] for row in strategy_equity] != [
        row["date"] for row in baseline_equity
    ]:
        raise ValueError("comparison requires identical observation dates")
    strategy = period_returns(strategy_equity, initial_cash)
    baseline = period_returns(baseline_equity, initial_cash)
    if len(strategy) < 2:
        raise ValueError("comparison requires at least two observations")
    finite(risk_free_annual, "risk_free_annual")
    if risk_free_annual <= -1:
        raise ValueError("annual risk-free rate must exceed -1")
    active = [left - right for left, right in zip(strategy, baseline)]
    active_deviation = statistics.stdev(active)
    base_variance = statistics.variance(baseline)
    strategy_deviation, base_deviation = statistics.stdev(strategy), statistics.stdev(
        baseline
    )
    strategy_mean, baseline_mean = statistics.fmean(strategy), statistics.fmean(
        baseline
    )
    covariance = sum(
        (left - strategy_mean) * (right - baseline_mean)
        for left, right in zip(strategy, baseline)
    ) / (len(strategy) - 1)
    beta = covariance / base_variance if base_variance > 0 else None
    risk_free_period = math.expm1(math.log1p(risk_free_annual) / periods_per_year)
    alpha = (
        (
            statistics.fmean(strategy)
            - risk_free_period
            - beta * (statistics.fmean(baseline) - risk_free_period)
        )
        * periods_per_year
        if beta is not None
        else None
    )
    return {
        "tracking_error": active_deviation * math.sqrt(periods_per_year),
        "information_ratio": (
            statistics.fmean(active) * math.sqrt(periods_per_year) / active_deviation
            if active_deviation > 0
            else None
        ),
        "beta": beta,
        "correlation": (
            covariance / (strategy_deviation * base_deviation)
            if strategy_deviation > 0 and base_deviation > 0
            else None
        ),
        "annualized_arithmetic_alpha": alpha,
        "assumptions": "Paired bar returns; sample covariance; arithmetic alpha relative to the stated baseline and constant risk-free rate. No causal attribution is implied.",
    }


def rolling_volatility(equity, initial_cash, window=20, periods_per_year=365):
    frequency(periods_per_year)
    if type(window) is not int or window < 2:
        raise ValueError("rolling window must be an integer of at least two bars")
    changes = period_returns(equity, initial_cash)
    output, observations = [], deque()
    mean, squared_deviations = 0.0, 0.0
    for index, item in enumerate(equity):
        if len(observations) == window:
            old = observations.popleft()
            remaining = len(observations)
            next_mean = (window * mean - old) / remaining
            squared_deviations -= (old - mean) * (old - next_mean)
            mean = next_mean
        change = changes[index]
        observations.append(change)
        delta = change - mean
        mean += delta / len(observations)
        squared_deviations += delta * (change - mean)
        value = (
            math.sqrt(max(squared_deviations, 0) / (window - 1) * periods_per_year)
            if len(observations) == window
            else None
        )
        output.append({"date": item["date"], "volatility": value})
    return output


def block_resample(
    equity, initial_cash, block_size=5, repetitions=500, seed=0, confidence=0.95
):
    if type(block_size) is not int or block_size < 1:
        raise ValueError("block_size must be a positive integer")
    if type(repetitions) is not int or not 20 <= repetitions <= 5000:
        raise ValueError("repetitions must be between 20 and 5000")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    finite(confidence, "confidence")
    if not 0 < confidence < 1:
        raise ValueError("confidence must lie between zero and one")
    changes = period_returns(equity, initial_cash)
    if block_size > len(changes):
        raise ValueError("block_size cannot exceed the observation count")
    if len(changes) * repetitions > 5_000_000:
        raise ValueError(
            "resampling budget exceeded; reduce repetitions or input length"
        )
    generator = random.Random(seed)
    results = []
    for _ in range(repetitions):
        selected = []
        while len(selected) < len(changes):
            start = generator.randrange(len(changes))
            selected.extend(
                changes[(start + offset) % len(changes)] for offset in range(block_size)
            )
        try:
            compounded = math.expm1(
                sum(math.log1p(value) for value in selected[: len(changes)])
            )
        except OverflowError as error:
            raise ValueError(
                "resampled return exceeds the supported numeric range"
            ) from error
        results.append(compounded)
    tail = (1 - confidence) / 2
    return {
        "lower": quantile(results, tail),
        "median": quantile(results, 0.5),
        "upper": quantile(results, 1 - tail),
        "confidence": confidence,
        "block_size": block_size,
        "repetitions": repetitions,
        "seed": seed,
        "interpretation": "Distribution of total returns under circular block resampling of the observed bars. This is not a confidence interval for future performance; it assumes the observed return process is suitable for resampling.",
    }
