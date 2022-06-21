# Request register

Source: Pavel, current project-planning chat, 2026-11-04.

| Request | Acceptance | Status |
|---|---|---|
| Build three substantial portfolio products | Independently usable implementations, meaningful verification and clear limits | In progress; Alphacairn has an initial working core |
| Distinctive names | Check indexed web and GitHub repository-name matches | `alphacairn` returned zero repository-name matches on 2026-11-04; not trademark clearance or a search-rank guarantee |
| Broad international scope | Concrete subsystem roadmap and independently extensible interfaces | Scope documented; scale and adoption not yet established |
| Detailed 2019–2026 allocation | Weekly deliverables, acceptance conditions and proposed commit dates | Written as an explicit reconstruction plan |
| Past-dated commits | Use reconstructed stage dates and preserve sole configured authorship | Initial local reconstructed stages created; author Pavel-Shcherbo (ID 44784481); no remote configured |
| Professional interface and documentation | Distinct product vocabulary, working controls, readable states and browser checks | Implemented; review in progress |
| Test independently; do not upload without Pavel | Local verification, no remote publication | Local checks in progress; upload withheld |

Requests from Julius or other team members: none in this project's current scope.

## Additional acceptance from Pavel

Each product must contain at least 20,000 useful production SLOC, excluding tests, documentation, fixtures, dependencies and generated outputs. Current implementations are far below this target. Broad implementation and independent verification remain in progress.

The contribution-date proposal allows 0–4 commits per day, rest days and breaks. It is a reconstruction plan, not completed historical work. The GitHub target is Pavel-Shcherbo; retain the existing author configuration. No upload without Pavel.

Implemented increment: 163 current tests passed; CLI and installed workbench entry points checked in a disposable clean environment. Current project-specific production source: 6956 SLOC, below 20,000. No publication.

Verified increment: exact-decimal portfolio journal, FIFO lots, explicit split/dividend/FX events, reconciliation and as-of valuation. 63 Alphacairn tests passed, including independent integer-cent controls, concurrent writers, replay corruption detection and isolated Decimal contexts. Installed CLI/HTTP checks passed; browser success, missing mark, statement discrepancy, delayed response and reproduced export passed. Evidence: `docs/verification.json`, `docs/installed-verification.json`, `docs/portfolio-browser-verification.json`, `docs/portfolio-export-verification.json`. The 20,000-SLOC and full product requirements remain open.

Verified increment: explicit-source market catalog, immutable raw batches, publication/recording clocks, revision-aware historical universes, portable snapshots and per-decision feature windows. 22 new subsystem tests and 85 total Alphacairn tests passed. Clean installed ingestion, decision windows, snapshot verification and fixed-vintage research passed. Evidence: `docs/MARKET_DATA.md`, `docs/market-catalog-verification.json`. Remote data adapters, corporate-action normalization, catalog UI, multi-asset simulation and the 20,000 useful-SLOC requirement remain open.

Verified increment: exact multi-instrument market/limit execution, known liquidity, partial fills, currency cash/position protection, per-fill fees, IOC/DAY/GTC, deferred cancellation/expiry, journal/FIFO/valuation reconciliation and deterministic replayable bundles. 28 new execution/export checks and 113 total Alphacairn tests passed. Installed CLI/export/replay and independent CSV Fraction accounting/final valuation passed. Evidence: `docs/EXECUTION.md`, `docs/execution-verification.json`. Additional strategy families, catalog UI, calendars/actions, initial holdings, execution UI and ≥20,000 useful SLOC remain open.

Verified increment: catalog-backed target-inventory studies with frozen per-decision universe/price vintages, separate realization prices, actual-fill sizing and explicit missing/stale-signal policies. Twenty-five new checks and 138 total Alphacairn tests passed. Clean installed capture/run/export/offline replay passed after deleting the source catalog; independent Fraction arithmetic over six fills reconciled USD 38.50 cash and USD 86.50 equity. A retained 10-instrument/50-decision/510-bar workload also replayed successfully. Evidence: docs/STRATEGIES.md, docs/strategy-verification.json, docs/strategy-benchmark.json. Strategy/catalog UI, additional policies, actions/calendars, initial holdings and broad product/20,000 useful-SLOC scope remain open.

Verified session-calendar increment: 25 new checks, 163 Alphacairn tests and installed CLI/export/offline replay passed. Explicit operator schedules cover closures, short/split/overnight/continuous sessions, strict gap/fold clocks, retained timezone rules and version-2 bar coverage. Independent Fraction accounting over the stock/crypto weekend control reconciled USD 30 cash and USD 107 equity. Evidence: docs/SESSIONS.md, docs/session-calendar-verification.json. Settlement cash flows, official exchange adapters, browser controls, corporate-action execution and full product/size scope remain open.
