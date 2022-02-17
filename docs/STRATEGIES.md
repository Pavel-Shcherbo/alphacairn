# Catalog-backed strategy studies

This path connects the versioned market catalog, decision-time features, state-aware order sizing and the reconciled execution journal. The included data is synthetic. Its deliberately unprofitable result is a control calculation, not a claim about a market strategy.

## Run a portable study

Export examples to a new directory, initialize a catalog and ingest the two explicit sources:

```sh
python3 -m alphacairn.resources ./demo
python3 -m alphacairn.market_cli --database .local/strategy-demo.sqlite init
python3 -m alphacairn.market_cli --database .local/strategy-demo.sqlite ingest synthetic-strategy bar demo/strategy-bars.json --request-key bars
python3 -m alphacairn.market_cli --database .local/strategy-demo.sqlite ingest synthetic-strategy membership demo/strategy-universe.json --request-key universe
python3 -m alphacairn.strategy capture demo/strategy-control.json --database .local/strategy-demo.sqlite --output .local/strategy-inputs.json
python3 -m alphacairn.strategy run .local/strategy-inputs.json --output .local/strategy-results
python3 -m alphacairn.strategy verify .local/strategy-results
```

Capturing inputs and writing a result bundle are create-only operations. Choose new output paths to retain another study. An existing output is never replaced. The verifier needs the portable bundle and installed package; it does not need the catalog, the original example files or network access.

## Configuration and information clocks

Version 1 requires an explicit source, historical universe, publication/recording clock, history start, lookback, maximum feature age and decision list. Decisions carry an absolute instant and a session label; instants must increase and labels cannot reverse. Lookback counts observations, not inferred trading days. Sessions, exchange holidays and settlement rules are not inferred. Weekend or delayed observations can become stale under the declared age policy.

Capture holds one coherent SQLite read view while collecting all required queries. Each decision gets its own universe and eligible bar revisions. The **published** clock trusts the provider-declared publication instant. The **recorded** clock additionally requires that the local catalog had ingested the observation by the cutoff. Loading synthetic 2020 data now cannot establish local availability in 2020; the recorded clock correctly refuses that claim.

The separate `market_cutoff` and `execution_sessions` choose the raw-price realization vintage used by the execution simulator. A later price revision may change simulated fills or historical valuations. It cannot replace earlier signal inputs. Every query retains its records, publication/recording times, batch identities and hashes. This permits exact portable replay; hashes do not authenticate an external provider or prove that an exported subset contains every observation the provider ever held.

The execution template uses the existing execution scenario fields except bars and commands. Instrument identities, currencies, costs, starting cash, time bounds, FX and mark freshness remain explicit. The adapter joins execution-vintage bars to an exact instrument/session liquidity declaration. Missing liquidity, extra declarations without bars, future-known liquidity and invalid price/clock envelopes fail validation. Realized volume is retained in source snapshots but is never substituted for a pre-open liquidity budget.

## Target-inventory policy

The built-in control strategy targets the configured positive quantity when the latest eligible close is strictly above its trailing mean; otherwise it targets zero. The comparison uses multiplication and the exact sum, avoiding a rounded mean changing the Boolean decision. Mean text is diagnostic. Features require the full lookback and an observation within `max_feature_age_seconds`; overlapping history bars are rejected.

`missing_signal_policy` explicitly selects **hold** or **exit** for missing/stale signals. An instrument leaving the historical universe targets zero. Every historical member must have a declared account instrument and target; missing instruments fail the study rather than silently dropping failed or delisted constituents. Inactive instruments remain in the decision trace, and no liquidation is invented after trading stops.

Orders are market IOC instructions for the difference between target inventory and actual holdings after earlier fills. A target of three shares with a previous partial fill of two therefore produces a later sell of two when the target becomes zero. A live order awaiting its first eligible open defers another instruction for that instrument. A signal change does not rewrite an already submitted order.

`allocation_order` lists every account instrument exactly once. It determines the command order for decisions sharing a timestamp; older pending orders retain the execution engine's submission-time priority. Orders share actual quote-currency cash and explicitly known liquidity. No borrowing, shorting or automatic FX exchange is added. Fees can prevent a small purchase or sale. A requested target is not a promise that the target was filled.

At a shared instant, expiry and bar closes precede decisions, and decisions precede opens. An order is eligible only at a strictly later open. A decision made exactly at an open cannot use that open. Instructions submitted after the final eligible open remain open and visible; terminal portfolio values do not assume forced liquidation.

## Replay and accounting

The planning pass advances the existing execution book chronologically to observe actual cash, holdings and pending orders. It emits a fully normalized, explicit order scenario. A second pass executes that scenario through the ordinary simulator. Fills, order states, cash, positions, liquidity, events and ledger events must match the planning pass. The simulator then independently reconstructs the portfolio through the durable journal and valuation path.

`strategy-report.json` retains the decision features, membership identities, positions/cash before each decision, target differences, reasons and submitted order IDs. `decisions.csv` provides the corresponding inspection table. The nested `execution` bundle contains the explicit scenario, fills, orders, equity curve and ledger events. The final manifest hashes every file.

Verification reads bounded ordinary files, checks inventory and hashes, recomputes signals and orders from captured inputs, re-executes the strategy and independently verifies the nested execution export. Changing a report or CSV and updating its manifest hash does not pass replay. Bundle integrity is content integrity, not a digital signature or a statement about source licensing.

## Synthetic control

Two instruments share USD cash: one stock with a one-share increment and one crypto spot instrument with a half-unit increment. Four decisions generate six partial/full fills. Every fill incurs a 0.50 USD fee.

| Fill | Cash effect, USD |
|---|---:|
| Buy 2 stock units at 13 | −26.50 |
| Buy 1 coin unit at 23 | −23.50 |
| Sell 2 stock units at 9 | +17.50 |
| Buy 0.5 coin unit at 25 | −13.00 |
| Buy 3 stock units at 15 | −45.50 |
| Sell 1.5 coin units at 20 | +29.50 |

Starting with 100.00 USD leaves 38.50 USD cash. The remaining three stock units are marked at 16, producing 86.50 USD equity. Total fees are 3.00 USD. These figures are also checked using independent rational arithmetic over the exported fills CSV.

## Limits and remaining work

A study supports at most 100 instruments, 100 decisions, a 1,000-observation lookback, 10,000 execution bars, 1,000 generated orders and two million order/bar evaluations. Captured inputs contain at most 100,000 retained observations and 16 MiB of canonical content; formatted input files must also fit 16 MiB. Strategy reports and decision CSVs are capped at 32 MiB and 8 MiB respectively. The complete bundle is capped at 128 MiB; nested execution limits also apply. Partition larger studies rather than dropping evidence.

Raw-price corporate actions, session/settlement calendars, real feed adapters, initial holdings, additional strategy families, parameter fitting and the strategy browser workspace remain executable work. This increment provides a real CLI workflow; it does not connect broker accounts or submit live orders.

Verification evidence: [installed study and independent arithmetic](strategy-verification.json), [current package checks](verification.json), and `tests/test_strategy.py`. Broad platform acceptance and 20,000 useful production SLOC remain open.

## Local workload observation

The retained [workload measurement](strategy-benchmark.json) uses 10 synthetic instruments, 50 decisions, 510 execution bars, 560 snapshots and 14,260 retained observations. Inputs occupy 7,401,521 canonical bytes; 140 orders produced 140 fills. On the recorded macOS arm64/Python 3.14.6 process, capture/validation took 0.874 seconds, planning with accounting 0.328 seconds, export 0.329 seconds and offline replay 0.394 seconds. Process peak RSS was 206,585,856 bytes. This is one local observation, not a throughput guarantee. The report records source hashes and the retained local bundle path.

Current verification: 25 strategy checks and 138 total Alphacairn checks passed, plus clean installed CLI/HTTP and independent CSV arithmetic. The strategy workflow is available through the CLI; a strategy browser screen remains open work.
