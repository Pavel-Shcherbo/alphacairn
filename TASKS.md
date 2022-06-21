# Tasks

Updated: 2026-11-04. Actual status only; historical roadmap rows remain proposed.

| Task | Status | Evidence | Remaining work |
|---|---|---|---|
| Core domain path | Implemented; 163 current tests passed | `alphacairn/`, `tests/` | Expand adversarial coverage as the model grows |
| Local CLI | Implemented; CLI end-to-end checks passed | `alphacairn/__main__.py`, `examples/` | Retained in the local verification evidence |
| Local workbench | Implemented; local HTTP and reviewed browser flows passed | `alphacairn/web.py`, `alphacairn/static/` | Retain checks as new screens and flows are added |
| Broad product scope | Planned | `docs/PRODUCT_SCOPE.md` | Most platform subsystems require implementation |
| Weekly reconstruction plan | Written | `docs/proposed-weekly-roadmap.csv` | Proposed commit counts are not actual commits |
| Publication | Waiting on Pavel | Current request: do not upload without Pavel | No push or hosted deployment |
| Production implementation ≥20,000 useful SLOC | Not achieved | 6956 project-specific SLOC measured; not achieved | Implement and verify the broad subsystem scope without padding |
| Risk analytics | Implemented; control-case tests passed | `alphacairn/analytics.py`, `tests/test_analytics.py` | Assumptions and browser comparisons documented; expand risk estimation with multi-asset inputs |
| Walk-forward studies | Implemented; timing and cash-reconciliation tests passed | `alphacairn/walkforward.py`, `tests/test_walkforward.py` | Browser workflow and installed CLI verified; untouched final holdout and expanded research registry remain open |
| Installable local package | Verified from a clean environment outside the source tree | `docs/installed-verification.json`, `_build.py`, `MANIFEST.in` | Cross-version/platform qualification remains open |
| Exact-decimal portfolio journal | Verified local increment; 63 total tests passed | `docs/PORTFOLIO.md`, journal/valuation/CLI/workbench tests and retained evidence | Historical valuation, corporate-action ingestion, settlement calendars, broker adapters and broader scope remain open |

| Versioned market catalog and decision windows | Verified local increment; 22 new checks, 85 total tests | `docs/MARKET_DATA.md`, `docs/market-catalog-verification.json` | Feed adapters, corporate-action normalization, calendars and catalog UI remain open |

| Multi-instrument order execution and replay | Verified local increment; 28 new checks, 113 total tests | `docs/EXECUTION.md`, `docs/execution-verification.json` | Additional strategy families, catalog UI, actions/calendars, initial holdings and browser controls remain open |

| Catalog-backed target-inventory strategies | Verified local increment; 25 new checks, 163 total current tests | `docs/STRATEGIES.md`, `docs/strategy-verification.json`, `docs/strategy-benchmark.json` | Strategy/catalog browser, additional policies, corporate actions/calendars, initial holdings and full product/size scope remain open |

| Retained trading sessions and execution coverage | Verified local increment; 25 new tests, 163 total current tests | `docs/SESSIONS.md`, `docs/session-calendar-verification.json` | Official calendar adapters, intraday pricing, settlement, browser controls and full scope remain open |

Next executable increment: expose saved market/strategy/execution controls in the workbench and implement corporate-action-aware execution, settlement calendars and additional strategy families.

Local reconstruction: five initial substantive stage commits created, plus verification, sequential research, portfolio-accounting, market-catalog, execution-engine and catalog-backed strategy increments. No remote is configured; no upload was performed. The full dated roadmap remains proposed.

Current implementation verification: 163 tests passed, CLI checked, clean wheel installation and installed workbench HTTP checked. Broad scope and the 20,000-SLOC requirement remain open.

Verified increment: exact-decimal portfolio journal, FIFO lots, explicit split/dividend/FX events, reconciliation and as-of valuation. 63 Alphacairn tests passed, including independent integer-cent controls, concurrent writers, replay corruption detection and isolated Decimal contexts. Installed CLI/HTTP checks passed; browser success, missing mark, statement discrepancy, delayed response and reproduced export passed. Evidence: `docs/verification.json`, `docs/installed-verification.json`, `docs/portfolio-browser-verification.json`, `docs/portfolio-export-verification.json`. The 20,000-SLOC and full product requirements remain open.

Verified increment: explicit-source market catalog, immutable raw batches, publication/recording clocks, revision-aware historical universes, portable snapshots and per-decision feature windows. 22 new subsystem tests and 85 total Alphacairn tests passed. Clean installed ingestion, decision windows, snapshot verification and fixed-vintage research passed. Evidence: `docs/MARKET_DATA.md`, `docs/market-catalog-verification.json`. Remote data adapters, corporate-action normalization, catalog UI, multi-asset simulation and the 20,000 useful-SLOC requirement remain open.

Verified increment: exact multi-instrument market/limit execution, known liquidity, partial fills, currency cash/position protection, per-fill fees, IOC/DAY/GTC, deferred cancellation/expiry, journal/FIFO/valuation reconciliation and deterministic replayable bundles. 28 new execution/export checks and 113 total Alphacairn tests passed. Installed CLI/export/replay and independent CSV Fraction accounting/final valuation passed. Evidence: `docs/EXECUTION.md`, `docs/execution-verification.json`. Additional strategy families, catalog UI, calendars/actions, initial holdings, execution UI and ≥20,000 useful SLOC remain open.

Verified increment: catalog-backed target-inventory studies with frozen per-decision universe/price vintages, separate realization prices, actual-fill sizing and explicit missing/stale-signal policies. Twenty-five new checks and 138 total Alphacairn tests passed. Clean installed capture/run/export/offline replay passed after deleting the source catalog; independent Fraction arithmetic over six fills reconciled USD 38.50 cash and USD 86.50 equity. A retained 10-instrument/50-decision/510-bar workload also replayed successfully. Evidence: docs/STRATEGIES.md, docs/strategy-verification.json, docs/strategy-benchmark.json. Strategy/catalog UI, additional policies, actions/calendars, initial holdings and broad product/20,000 useful-SLOC scope remain open.

Verified session-calendar increment: 25 new checks, 163 Alphacairn tests and installed CLI/export/offline replay passed. Explicit operator schedules cover closures, short/split/overnight/continuous sessions, strict gap/fold clocks, retained timezone rules and version-2 bar coverage. Independent Fraction accounting over the stock/crypto weekend control reconciled USD 30 cash and USD 107 equity. Evidence: docs/SESSIONS.md, docs/session-calendar-verification.json. Settlement cash flows, official exchange adapters, browser controls, corporate-action execution and full product/size scope remain open.
