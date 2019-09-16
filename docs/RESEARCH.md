# Research method

## Timing and accounting

The moving-average signal observes closes through the previous bar. Trades use
the next bar's open with a declared slippage adjustment. Positions are long-only
and fractional. Cash, quantity and marked position value are retained in equity
observations. Signal timestamps precede the opening fills they generate.

Fixed-parameter studies leave the last position marked at the last close.
Sequential studies have an explicitly scheduled close-out at each test-window
boundary; sell slippage and fees are included. The next window starts flat with
the previous window's final cash. This rebalance convention can differ materially
from continuous holding and is included in exported assumptions.

## Walk-forward selection

Each training window ends before its test window begins. Candidate lookbacks are
scored on the training window alone, including declared costs. The selected
candidate is evaluated on the next, disjoint test window. Previous training
prices warm the indicator without allowing training-period trades into test
equity. The final shorter test window is retained.

Ties select the smaller lookback deterministically. Undefined scores are not
silently treated as zero. Candidate counts and an evaluation-work budget are
explicit. Parameter selection does not establish a trading advantage, and a
separate untouched final holdout is not created automatically.

## Descriptive risk

Annualization uses a declared daily-bar frequency, such as 365 for continuous
daily observations or the 252 trading-day convention. It does not infer a market
calendar or calculate an exact elapsed-time CAGR from date-only bars.

Volatility uses sample standard deviation. Sharpe uses per-period excess returns
against the declared constant annual risk-free rate. Sortino uses the root mean
square of negative excess returns, including zero contributions from other bars.
Ratios with zero denominators are undefined and remain null in JSON.

Historical tail loss is the negative empirical return quantile with linear
interpolation. Expected shortfall is the negative mean of observed returns at or
below that threshold. With all positive observations these descriptive loss
measures can be negative. Small samples provide limited tail evidence.

Baseline comparisons pair identical dates. Beta uses sample covariance and
baseline variance; arithmetic alpha is frequency-scaled and is not a causal effect.
Rolling volatility uses only observations through its displayed date.

Circular block resampling preserves short adjacent runs within each selected
block. Its interval describes resampled totals from the observed process. It is
not a confidence interval for future strategy returns.

## Provenance and limits

The normalized dataset identity hashes the validated date/open/close records.
Original-file and received-text hashes are separate because line endings, textual
number formatting and transport can differ without changing used observations.

The bundled market series is synthetic. Corporate actions, historical universes,
delisted securities, realistic liquidity constraints, borrowing and derivative
margin are not implemented. Do not interpret the current simulator as a qualified
equities or derivatives execution model. No real orders are sent.
