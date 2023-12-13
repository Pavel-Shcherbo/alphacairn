# Journal-backed multi-asset risk

Capture a coherent journal state, explicit current quotes, an operator-supplied history and a risk configuration. The study reconstructs the accepted journal events before valuing exposures. It then reports concentrations, deterministic stress scenarios, descriptive covariance risk and signed historical tail losses.

## Run the synthetic control

```sh
python3 -m alphacairn.portfolio --db .local/risk-ledger.sqlite init examples/portfolio-account.json
python3 -m alphacairn.portfolio --db .local/risk-ledger.sqlite apply examples/portfolio-events.json
python3 -m alphacairn.risk capture examples/risk-control.json \
  --database .local/risk-ledger.sqlite --history examples/risk-history.json \
  --quotes examples/risk-quotes.json --output risk-inputs.json
python3 -m alphacairn.risk run risk-inputs.json --output risk-results
python3 -m alphacairn.risk inspect risk-inputs.json
python3 -m alphacairn.risk verify risk-results
```

After installation, export examples with `python3 -m alphacairn.resources demo` and use the `demo/` paths. Input exports and result directories are create-only. The synthetic account has 10,948.90 USD marked equity. The declared joint price/FX drop produces 9,589.61 USD, a loss of 1,359.29 USD. A EUR-only shock loses 109.89 USD. These are hand-checkable synthetic scenarios, not historical investment results.

## Capture and provenance

The source SQLite journal is opened read-only and copied through a coherent SQLite backup, including committed WAL content. The private copy is used to read account specification, accepted events, receipts and current state. Payload hashes, event identities and persisted posting lists are checked. The accepted events are independently replayed, and replayed receipts and state must agree. Capturing does not write to the original journal.

Portable inputs retain all captured events and state, quotes, history and normalized configuration with a content hash. Historical state must be captured or reconstructed at the intended time: a current journal containing events after `as_of` is refused during valuation. Capture retains data; running the study additionally validates valuation and estimation requirements. No assumption is made that externally supplied marks or history are authentic merely because their file hashes agree.

Captured inputs and result bundles include raw financial data. Keep synthetic or appropriately reviewed inputs when sharing a portfolio example. File exports use a temporary file and atomic create-only publication; bundle directories are private and incomplete bundles without their exact manifest are rejected.

## Definition and quotes

The version 1 configuration explicitly sets `name`, `as_of`, `max_age_seconds`, `history_start`, `history_end`, `periods_per_year`, `confidence`, `shrinkage`, `min_observations`, `max_gap_days`, `concentration_limits` and `scenarios`.

- The historical window satisfies `history_start < history_end <= as_of`.
- Quote age is 0–366 days. Future quotes are invalid; missing or stale required quotes produce an incomplete baseline.
- Frequency is 1–366 periods per year. It is an operator assumption about the supplied observations.
- Confidence lies strictly between 0 and 1. Shrinkage lies between 0 and 1, inclusive.
- Minimum complete return observations are 2–1,000. Adjacent timestamp gaps may be at most the declared 1–31 days.

Quotes contain `as_of`, `marks`, `fx` and `max_age_seconds`, with the same clock/age as the configuration. Their mark/rate timestamp contracts are the existing portfolio valuation contracts. FX rates are base-currency units per one unit of the quote currency. Prices and rates use decimal text, never binary floats.

Current positions, cash and outstanding net dividend assets reconcile exactly to the existing journal valuation. The estimator currently supports 24 active risk factors: one per held instrument plus one per foreign currency with cash/dividend assets. Base-currency cash is deterministic in this model. Foreign positions use their own base-currency return factor, including FX, rather than counting a separate FX exposure twice.

## Historical observations

History version 1 requires `source`, `price_basis: "split_adjusted_price_only"` and ordered `observations`. Each observation has `at`, `available_at`, `prices` and `fx`. Observation times strictly increase; availability cannot precede the observation. Each retained instrument price and currency rate is positive decimal text or null. Missing keys also mean missing inputs.

Only adjacent original observations can form one shock. Both endpoints must lie within the selected window, be available at the study's `as_of`, include every active factor input and satisfy the gap bound. An unavailable or missing point excludes both adjacent intervals; the estimator never joins over it or forward-fills a price. Excluded intervals retain their reasons, and the report identifies the actual interval endpoints used.

The source is an operator-supplied synchronous history. Upstream revision selection, compatible observation clocks and split adjustment must be reviewed before capture; the module does not independently certify these declarations. Raw split discontinuities, income reinvestment and calendar alignment are not silently corrected. Equity and continuous crypto histories must be deliberately aligned. This increment does not add a provider or market-catalog adapter.

For a position factor, the simple base-currency return is:

`r = (price_next * FX_next) / (price_previous * FX_previous) - 1`.

For foreign cash/dividend assets it is `FX_next / FX_previous - 1`. Base-currency FX is exactly 1. Returns are rounded half-even to 12 decimal places before estimation. This common grid keeps arithmetic bounded and reproducible. A hypothetical historical P&L is the sum of current marked base exposures multiplied by these factor returns. It does not reconstruct the portfolio's old holdings or realized returns.

## Covariance and contribution calculations

The sample covariance uses centered returns and denominator `n-1`. Declared diagonal shrinkage computes `(1-a) * sample + a * diag(sample)`: off-diagonal entries shrink while each diagonal variance stays unchanged. Both matrices are reported. No shrinkage coefficient is fitted or selected from the reported result.

For current factor values `x`, portfolio variance is `x' * covariance * x`. Factor variance contribution is `x_i * (covariance * x)_i`; these contributions sum exactly to portfolio variance. A hedge can have a negative contribution, which is preserved. Component volatility divides the variance contribution by portfolio volatility. At zero portfolio variance, those normalized components and shares are null.

Matrices, variance contributions and tail calculations use exact rational arithmetic on the rounded return grid. Exact numerator/denominator fields accompany displayed covariance and variance values. Square roots use an isolated 80-digit decimal context; displayed diagnostics use 18 decimal places. Caller Decimal settings do not change results.

The report records sample and regularized ranks, zero-variance factors and the one-norm condition number when invertible. A condition number of at least 100,000,000 is marked ill-conditioned. Singular matrices remain explicit, with no invented inverse or hidden fallback. Portfolio variance does not require an inverse, so a singular matrix can still produce a valid descriptive variance. Undefined correlations are null. Reported correlations correspond to the regularized matrix.

Annualized volatility is `sqrt(periods_per_year * variance) / equity`, under the declared equal-period and no-serial-correlation approximation. It is not an independently validated future-risk estimate. The sample covariance convention follows the [NIST multivariate-statistics handbook](https://www.itl.nist.gov/div898/handbook/pmc/section5/pmc541.htm).

## Historical tail convention

Loss is negative static-exposure hypothetical P&L. With `n` equally weighted observations and confidence `c`, VaR is the `ceil(c*n)` order statistic in ascending losses. Expected shortfall integrates the worst `(1-c)*n` observation mass. A fractional boundary observation receives only the remaining mass; its weight is retained in the report. This convention is explicit rather than dependent on a library's quantile default.

Signed gains are not floored to zero. In the bundled toy hedge, every observed hypothetical P&L is positive, so both 95% VaR and ES are negative 5.71 USD. This describes that tiny sample only. The report flags a tail mass below five observations. It does not extrapolate unobserved extremes or claim regulatory capital qualification.

## Concentration and stress scenarios

Concentration groups cover instrument, currency, venue and asset kind. Each configured limit is a fraction of total marked equity, including cash and dividend assets. Breaches are review findings, not permission to trade. Zero/nonpositive equity has no invented weights. A held position marked at zero makes the relative-return estimator explicitly incomplete; it is not reclassified as a cash-only portfolio. Declared percentage stresses can still be evaluated.

Each of 1–32 stress scenarios has a unique `id`, `price_shocks` and `fx_shocks`. Relative price changes support -100% through +1,000%; FX changes support greater than -100% through +1,000%. Base-currency FX shocks are refused. Joint shocks compound: a foreign asset's changed price is converted at the changed FX rate. Current holdings and accrued dividend amounts remain fixed.

Stressed per-unit quotes are rounded half-even to 18 places, then the existing valuation engine applies instrument-currency and base-currency rounding. Every cash/position/dividend component P&L must reconcile to the stressed equity difference. Unused declared shocks are listed. Missing baseline marks/FX block stressed equity, rather than presenting a known subset as the complete result. Liquidity, spread changes, credit events, derivative convexity, settlement and stressed trading decisions are outside this model.

## Exports, completion and bounds

A result bundle contains exact `inputs.json`, `risk-report.json`, `exposures.csv`, `stresses.csv`, `history.csv` and `manifest.json`. Verification checks file inventory and byte hashes, reconstructs the accepted journal, reruns valuation and all calculations, and requires the CSV/JSON bytes to match deterministic output. Original journal and history files are unnecessary after capture.

A valid incomplete report can replay successfully while retaining `complete: false`. Insufficient history does not invalidate independently completed stresses. The CLI returns 0 for a complete result (or a successful capture), 1 for a reproducible incomplete result and 2 for invalid inputs, evidence or I/O failures. Hashes and replay do not authenticate provider identity or prove prediction accuracy.

The capture is bounded to 10,000 journal events, 200,000 postings, a 32-MiB source database/WAL limit and a ten-second backup budget. Portable inputs/files are at most 16 MiB, with bounded JSON structure. History has at most 1,001 points, covariance uses at most 24 factors/600,000 factor-pair observations, and matrix intermediates have a 16,384-bit rational limit. Bundles including their manifest are capped at 48 MiB. Unsupported numeric or file sizes fail explicitly. Other instrument classes, provider histories, browser risk review, long-running study jobs and full platform scope remain open.

## Retained verification

Thirty-four risk tests cover independently reconciled monetary shocks, signed empirical losses, hand-calculated sample covariance, negative contributions, fractional tail mass, singular/ill-conditioned/zero-variance cases, diagonal shrinkage, missing/unavailable/gapped data, stale/future quotes, cash-only and zero-equity behavior, dividend receivables, journal corruption, WAL capture, Decimal-context isolation, create-only exports, rehashed tampering and complete/incomplete CLI exit behavior.

`risk-verification.json` records clean installed CLI checks and independent CSV/integer-cent controls, including replay after removing the source ledger. `risk-benchmark.json` retains a 24-factor/1,000-return workload, an independent variance calculation and its offline replay. Local timing measurements are not an execution SLA. Existing platform and ≥20,000 useful-production-SLOC requirements remain tracked separately.
