# Frozen research attempts

The local research registry retains every registered attempt, its exact inputs and its terminal outcome. It supports the existing multi-asset risk and captured strategy engines. A completed but incomplete risk report remains a distinct outcome; a failed computation is retained with its error. Comparisons include every registered trial in registration order rather than presenting only a selected winner.

This is a CLI workflow. The study browser, global dataset-access tracking, remote identities, multi-user permissions and formal statistical validation are not implemented by this increment.

## Run a declared study

First capture `risk-inputs.json` using the [risk guide](RISK.md), or capture strategy inputs with the [strategy workflow](STRATEGIES.md). Then:

```sh
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  create examples/study-risk-plan.json
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  register STUDY risk-inputs.json --partition development \
  --request-key baseline --label "Fixed baseline"
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  run TRIAL --actor reviewer --reason "Execute declared baseline"
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  compare STUDY --actor reviewer --reason "Review every development attempt"
```

Replace `STUDY` and `TRIAL` with returned IDs. After package installation, export examples with `python3 -m alphacairn.resources demo` and use `demo/` paths. The bundled study and financial inputs are synthetic. A declaration can be entered after its observations already exist: this registry records workflow order, not preregistration before real-world data release.

## Immutable declarations and input identities

A version 1 study declaration contains `name`, `family`, `hypothesis`, `development` and `holdout`. Each window has explicit UTC-offset `start` and `end` values. Development must end strictly before the holdout begins; the boundaries cannot overlap. Reusing a study name within its project is idempotent only for the same immutable declaration.

Risk trial window membership covers the estimator's `history_start` through its portfolio `as_of`. Strategy membership covers execution `starts_at` through `ends_at`; legitimate preceding signal history remains part of its captured inputs. Every trial must fit wholly within its declared partition.

Registration accepts a complete frozen input document and an idempotency key. Its input SHA-256 is the actual captured document identity. The request additionally binds partition and label. Equal retries return the same trial; reusing the key for different inputs, labels or partitions fails. Invalid declarations/input formats are rejected before registration and do not count as research attempts. Valid registered inputs that fail during computation remain visible as failed trials.

Source inputs are immutable through the API. Runs use those retained bytes, never mutable external paths or the latest market-catalog revision. Cached result reads check input identity, registration binding, the study event chain and committed completion identity before returning a result.

## Results and complete comparisons

Run states are `registered`, `running`, `succeeded`, `incomplete`, `failed` and `interrupted`. The runner supports:

- **Risk:** current journal replay, valuation, concentrations, stresses and descriptive covariance/tail statistics. A complete baseline with insufficient history remains `incomplete`.
- **Strategy:** captured decision vintages and independently replayed order execution. Missing final valuation inputs prevent a successful qualification.

A repeated run of a terminal trial returns the saved result without another computation. To test a changed input, register another request key so the attempt remains part of the denominator. A retry of the same development result is observational; a holdout result retry is also recorded as a holdout access attempt.

`compare` returns all registered trials, including pending, failed, incomplete and interrupted attempts. It includes summary metrics for development results and preserves errors. The summaries are not a scoring rule: risk studies show equity, variance and worst declared stress P&L; strategies show final equity and fill count. A summary is not an estimate of future performance. The tool does not automatically choose a winner or correct for multiple testing.

## Lock the selection before opening a holdout

```sh
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  select TRIAL --study STUDY --actor reviewer --reason "Freeze reviewed method"
```

Selection requires a successful development trial in this study. Every registered development attempt must first be terminal, including failed and interrupted attempts. Locking closes development registration and cannot be replaced through the API. Repeating an old registration key can still retrieve its existing record, but cannot add another trial.

Only then may a holdout trial be registered. Its method recipe must match the selected development trial. For risk, the recipe retains the account and risk settings while excluding study name and the three changing window/valuation timestamps. Quotes, journal events and historical observations remain retained data, not recipe settings.

For strategy, the recipe retains source/universe, signal settings, account, cost assumptions, target sizing, allocation and missing-signal policy. It excludes signal history start, decisions, market cutoff, execution-session dates and liquidity observations; execution start/end, FX observations and corporate-action records are also treated as data. All removed fields remain present in the original captured document. Calendar definitions and other execution settings remain fixed. This declared recipe comparison cannot universally distinguish every modeling decision from every data choice; review liquidity/action interpretation and data provenance explicitly.

## Holdout access is visible and scoped

Default overview and comparison expose holdout metadata but withhold its numerical results and error contents. Opening inputs, running, rereading a run result, explicit comparison with `--include-holdout`, and exporting a holdout trial each record an access attempt with an operator-supplied actor and reason.

```sh
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  compare STUDY --include-holdout --actor reviewer --reason "Open final verification results"
python3 -m alphacairn.studies --database .local/studies.sqlite --project research events STUDY
```

The count is conservative: it counts accepted access requests, including a result retry, rather than claiming to count unique human observations. Registration and metadata listing do not open a result. `holdout_registry_unopened` means zero registered access attempts **for this study**; it says nothing about original files, access through other tools or another study. Creating another study is not a fresh-data or global blindness guarantee. Actor/reason fields are local annotations, not authenticated identities.

## Interruption and ownership

Starting a computation atomically records ownership and its start event. Completion commits the result and event in one SQLite transaction, with a ten-minute ownership lease checked again before commit. Concurrent starts cannot both acquire one trial. Expired workers cannot publish a later result.

A crash or interrupt leaves the attempt visible as running until explicit reconciliation:

```sh
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  recover TRIAL --generation N --actor reviewer --reason "Reconcile expired local worker"
```

Only an expired running trial at the expected generation can become `interrupted`. Recovery does not rerun the computation or claim that a missing result passed. The attempt stays in the comparison. To retry execution, register a new request so the original interruption is not erased.

## Audit and portable evidence

```sh
python3 -m alphacairn.studies --database .local/studies.sqlite --project research audit STUDY
python3 -m alphacairn.studies --database .local/studies.sqlite --project research \
  export TRIAL --output study-evidence.json --actor reviewer --reason "Independent review"
python3 -m alphacairn.studies verify study-evidence.json
```

Audit reads one coherent snapshot, validates retained input/result identities, chain order, attempt states, selection timing, method binding and holdout access totals. It does not recalculate every trial. Export retains the selected trial's exact inputs/result plus the complete bounded attempt/selection/access context of its study. It includes the identities and states of the other attempts rather than their raw data/results.

Offline verification checks the context and recomputes the exported trial with the original engine. A reproducible failed/incomplete attempt may have valid evidence without becoming successful. An interrupted attempt has no fabricated execution replay; an attached uncommitted result is rejected. The original registry database is unnecessary after export. Rehashed edits to trial results, omitted attempts, changed selection context or inconsistent access totals are rejected when inconsistent with the retained evidence. Hashes are not external signatures or a guarantee against rewriting an entire private database/history; `source_authenticated` is false.

Exports are create-only and contain raw financial inputs. CLI status 0 means a successful operation or successful completed trial; 1 indicates failed/incomplete/interrupted trial qualification or incomplete evidence; 2 indicates invalid input, evidence or I/O failure. A valid failed-trial export verifies its retained computation while returning 1 for qualification.

## Bounds and retained verification

A local database is capped at 256 MiB, with 200 studies and 100 registered trials per study. Trial inputs are at most 16 MiB, results at most 32 MiB, portable evidence at most 72 MiB. Complete audits retain at most 20,000 events per study and refuse larger histories as complete audits. Underlying engine arithmetic/input budgets still apply. Retention/deletion and longer-running job services remain unfinished platform work.

Twenty new tests cover request identity, project boundaries, complete outcome denominators, pending selection guards, locked methods, per-study holdout access, default result withholding, repeated result reads, source/result tampering, export without the registry, omitted attempt/access context, interruptions, lease expiry, concurrency, real strategy execution and CLI use. The captured strategy control independently ends at 86.50 USD with six fills; the risk control ends at 10,948.90 USD.

`research-registry-verification.json` records clean installed CLI and independent SQLite status/access counts, protected comparisons, fixed selection and offline verification. `research-registry-benchmark.json` retains a 50-attempt workload: 17 successful, 17 incomplete and 16 failed attempts, all present in comparison and audit. Timings are one local observation, not a production SLA or statistical discovery claim. Full platform and ≥20,000 useful-production-SLOC acceptance remain open.
