# Initial-core verification

Verified locally on 2026-11-04. This is not full product acceptance.

- 85 domain, integration and negative-path tests passed.
- The documented CLI control scenario completed and its result was checked.
- Local HTTP success/failure scenarios and foreign-Origin rejection were checked.
- Desktop and mobile workbench screens were inspected; the review includes defect corrections.
- Broader product scope and the 20,000 useful production-SLOC requirement remain incomplete.

Run `python3 -m unittest discover -s tests -v` from this checkout. The examples and README describe supported behavior and limits. No remote publication or hosted deployment was performed.

Version 0.2 wheel installation was checked in an independent virtual environment from an unrelated working directory. Example export, CLI, static files and public workbench calculations passed. Installed code matched the source files, and runtime state remained outside the package. See installed-verification.json for the wheel identity.

Portfolio verification includes hand-calculated multi-currency balances, FIFO partial-sale basis, split neutrality, dividend withholding, fees above sale proceeds, zero-price marks, missing/stale/future quote handling, concurrent cash spending, duplicate delivery, atomic batch rollback, cache/receipt corruption detection, 100 seeded trades against an independent integer-cent/Fraction model and isolated Decimal contexts. Installed CLI initialization/import/value/reconcile/audit passed. Browser export was downloaded and independently reproduced; mobile width, missing data, statement discrepancies and a controlled delayed-response race passed. See portfolio-browser-verification.json and portfolio-export-verification.json.

Verified increment: explicit-source market catalog, immutable raw batches, publication/recording clocks, revision-aware historical universes, portable snapshots and per-decision feature windows. 22 new subsystem tests and 85 total Alphacairn tests passed. Clean installed ingestion, decision windows, snapshot verification and fixed-vintage research passed. Evidence: `docs/MARKET_DATA.md`, `docs/market-catalog-verification.json`. Remote data adapters, corporate-action normalization, catalog UI, multi-asset simulation and the 20,000 useful-SLOC requirement remain open.

The market controls include a shuffled independent revision-timeline oracle, source separation, same-time conflicts, late corrections, retractions, half-open delisting intervals, overlapping-universe rejection, partial audits, raw/index tampering, concurrent ingestion and consistent read views. Browser evidence above applies to the existing strategy and portfolio screens; market catalog UI is not implemented.
