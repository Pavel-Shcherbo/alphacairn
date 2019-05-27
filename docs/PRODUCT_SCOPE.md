# Product scope

Proposed scope. Completion is tracked in TASKS.md; the weekly roadmap is not evidence of historical work.

## 2019: proposed development stages

### Q1: Market data model

Scope: daily bars, instrument identity and timestamp validation.

Acceptance: duplicate dates and invalid prices are rejected.

### Q2: Signal timing

Scope: previous-close decisions and next-open execution.

Acceptance: future observations cannot alter past positions.

### Q3: Portfolio accounting

Scope: cash, positions, fees and mark-to-market equity.

Acceptance: hand-calculated trades reconcile to portfolio equity.

### Q4: Research reports

Scope: baseline comparison, turnover and drawdowns.

Acceptance: reported performance includes the declared transaction costs.

## 2020: proposed development stages

### Q1: Data provenance

Scope: raw snapshots, manifests and transformation hashes.

Acceptance: a reported result identifies the exact source snapshot.

### Q2: Corporate actions

Scope: split and dividend adjustments with raw-price preservation.

Acceptance: adjustments do not create fictitious portfolio gains.

### Q3: Historical universes

Scope: listing intervals, symbol changes and delistings.

Acceptance: selection does not silently exclude failed companies.

### Q4: Trading calendars

Scope: exchange sessions, holidays and asset-specific clocks.

Acceptance: signals cannot execute outside the declared market schedule.

## 2021: proposed development stages

### Q1: Order simulation

Scope: market and limit orders with explicit fill assumptions.

Acceptance: OHLC bars are not treated as known intrabar price paths.

### Q2: Execution costs

Scope: spreads, slippage scenarios and liquidity constraints.

Acceptance: larger simulated orders do not assume unlimited available volume.

### Q3: Multi-asset portfolios

Scope: sizing, cash constraints and rebalance timing.

Acceptance: simultaneous orders cannot spend the same available cash twice.

### Q4: Crypto adapters

Scope: spot instruments, quote currencies and continuous sessions.

Acceptance: token aliases and changed contract identifiers remain distinguishable.

## 2022: proposed development stages

### Q1: Walk-forward evaluation

Scope: rolling training windows and subsequent test windows.

Acceptance: parameter fitting never observes the evaluation period.

### Q2: Experiment registry

Scope: immutable configurations and retained failed hypotheses.

Acceptance: the comparison view includes all registered runs.

### Q3: Parameter stability

Scope: neighboring configurations and transaction-cost sweeps.

Acceptance: a single isolated optimum is not presented as a robust finding.

### Q4: Multiple testing

Scope: trial counts, holdout policy and resampling diagnostics.

Acceptance: repeated holdout access invalidates its untouched status.

## 2023: proposed development stages

### Q1: Fundamental inputs

Scope: filing timestamps, restatements and as-of joins.

Acceptance: a financial fact becomes available only after its filing timestamp.

### Q2: Macro vintages

Scope: release calendars and revised historical observations.

Acceptance: the latest revised value is not substituted into a historical decision.

### Q3: Factor diagnostics

Scope: exposures, residual analysis and sector attribution.

Acceptance: factor estimation uses only the declared estimation interval.

### Q4: Risk estimation

Scope: covariance estimation and stress scenarios.

Acceptance: ill-conditioned estimates produce a warning or a defined fallback.

## 2024: proposed development stages

### Q1: Position constraints

Scope: bounds, turnover limits and cash buffers.

Acceptance: proposed weights satisfy constraints after cost accounting.

### Q2: Derivatives accounting

Scope: supported contract specifications, funding and margin.

Acceptance: contract units and margin cash flows reconcile on control examples.

### Q3: Strategy workspace

Scope: interactive charts, trade drilldown and comparison tables.

Acceptance: visible summaries reconcile to downloadable research outputs.

### Q4: Reproducible bundles

Scope: portable data subsets and executable experiment manifests.

Acceptance: a clean environment reproduces the published control experiment.

## 2025: proposed development stages

### Q1: Paper trading

Scope: simulated live decisions with persisted event timestamps.

Acceptance: stale inputs cannot silently trigger a current decision.

### Q2: Reconciliation

Scope: expected versus observed paper fills and positions.

Acceptance: divergences remain visible until explicitly resolved.

### Q3: Team research

Scope: workspace permissions and experiment review records.

Acceptance: private datasets are not exposed through shared reports.

### Q4: Model monitoring

Scope: feature drift, forecast decay and cost sensitivity.

Acceptance: monitoring reports uncertainty and data gaps alongside changes.

## 2026: proposed development stages

### Q1: Independent validation

Scope: predefined holdouts and adversarial data fixtures.

Acceptance: results survive the published timing and survivorship checks.

### Q2: Research API

Scope: versioned endpoints, job limits and result pagination.

Acceptance: cancelled jobs cannot publish an apparently complete result.

### Q3: Data licensing

Scope: dataset permissions and redistribution controls.

Acceptance: exported bundles exclude inputs that cannot be redistributed.

### Q4: Public examples

Scope: reviewed studies and transparent limitations.

Acceptance: no return or capacity claim lacks reproducible supporting evidence.
