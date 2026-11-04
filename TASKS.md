# Tasks

## Workbench port validation — 2026-11-05

Source: Pavel requested old-dated Issues and actual current-dated PR/reviews. Implemented and verified: invalid port values report a usage error with exit 2; automatic port zero remains runnable. All 327 current tests passed on CPython 3.14.6 / macOS arm64, including a real ephemeral-port HTTP startup regression.

- [Issue #2](https://github.com/Pavel-Shcherbo/alphacairn/issues/2) is explicitly disclosed reconstruction dated 2019-02-04; historical calendar credit is not claimed.
- [PR #1](https://github.com/Pavel-Shcherbo/alphacairn/pull/1) contains the implementation, documentation and regressions.
- [Author self-review](https://github.com/Pavel-Shcherbo/alphacairn/pull/1#pullrequestreview-5775873338) records the inspected boundaries and actual test result; no independent approval is claimed.

Implementation and scoped verification are complete; PR/issue lifecycle is recorded on GitHub. Future platform features remain backlog.

## Final acceptance review — 2026-11-04

Pavel explicitly requested skipping PR and review events and completing the final project/profile review. The previous historical-event blocker is withdrawn from acceptance. No new PR or review was created.

Verified source revision: `d6b21278f48a4bb5a9cf2def38afda9a8639f74a`. All 324 tests passed again on the local CPython interpreter. Browser study: 260 observations and 32 fills. Exact portfolio control: USD 10948.90, nine events and matched statement reconciliation. The application was visually inspected on desktop and at a 390 px viewport without horizontal page overflow. Published README navigation and the screenshot disclosure were inspected on GitHub. No runtime correction was required.

The current local scope is accepted; future platform features remain backlog. Final logs, screenshots and remote-blob comparisons are retained in the central final-review evidence. The existing verification guide records supported-version/platform qualification; this final control does not claim a hosted or multi-user deployment.

---


## Repository usability — 2026-11-04

Request: Pavel asked for further visual polish and repository collaboration features; pull requests and reviews must retain historical dates.

Implemented: task-oriented guide index, compact screenshot disclosure, contribution instructions and focused issue/PR templates. Local guide links, CLI help and whitespace checks passed. Runtime code and the qualified test evidence are unchanged. Publication/readback evidence is retained in the central request register. No current-dated PR or review is authorized or created. Historical PR/review import remains unconfirmed; that event-creation requirement is unresolved.


## Public repository status — 2026-11-04

Published with Pavel's explicit authorization at https://github.com/Pavel-Shcherbo/alphacairn.
The initial remote main matched qualified snapshot 3f129374fcab40e81754a4a4eb4c22f67224e3c3.
The implemented local scope is qualified as recorded in docs/VERIFICATION.md.
This status supersedes earlier publication holds in the historical register below.
Earlier dates are a disclosed reconstruction; this publication record uses its actual date.
GitHub contribution-calendar rendering is checked separately and is not implied by a push.
No remaining local delivery blocker; future scope remains backlog.

---

## Current local qualification — 2026-11-04

Implemented scope: decision-time market vintages, exact FIFO accounting, corporate actions, retained sessions, opening holdings, cash settlement and saved risk/research replay. Full project suites passed on CPython
3.10–3.14: 324 tests per version. Clean wheel installation and CLI/API controls
passed on 3.10 and 3.14. [Current evidence](docs/VERIFICATION.md) supersedes old
size requirements and historical test totals below. Final package identities are maintained in the central review register;
Publication is authorized and complete. Future provider/hosted/distributed
features in the original roadmap remain optional backlog.

---

## Archived development register

The rows below preserve earlier development snapshots. The current publication and qualification status is stated above; old holds, size thresholds and incomplete-feature notes are not current acceptance decisions.

| Task | Status | Evidence | Remaining work |
|---|---|---|---|
| Core domain path | Implemented; 324 current tests passed | `alphacairn/`, `tests/` | Expand adversarial coverage as the model grows |
| Local CLI | Implemented; CLI end-to-end checks passed | `alphacairn/__main__.py`, `examples/` | Retained in the local verification evidence |
| Local workbench | Implemented; local HTTP and reviewed browser flows passed | `alphacairn/web.py`, `alphacairn/static/` | Retain checks as new screens and flows are added |
| Broad product scope | Planned | `docs/PRODUCT_SCOPE.md` | Most platform subsystems require implementation |
| Weekly reconstruction plan | Written | `docs/proposed-weekly-roadmap.csv` | Proposed commit counts are not actual commits |
| Publication | Waiting on Pavel | Current request: do not upload without Pavel | No push or hosted deployment |
| Production implementation ≥20,000 useful SLOC | Not achieved | 12914 project-specific SLOC measured; not achieved | Implement and verify the broad subsystem scope without padding |
| Risk analytics | Implemented; control-case tests passed | `alphacairn/analytics.py`, `tests/test_analytics.py` | Multi-asset risk verified; extend provider histories and browser risk controls |
| Walk-forward studies | Implemented; timing and cash-reconciliation tests passed | `alphacairn/walkforward.py`, `tests/test_walkforward.py` | Browser workflow and installed CLI verified; untouched final holdout and expanded research registry remain open |
| Installable local package | Verified from a clean environment outside the source tree | `docs/installed-verification.json`, `_build.py`, `MANIFEST.in` | Cross-version/platform qualification remains open |
| Exact-decimal portfolio journal | Verified local increment; 63 total tests passed | `docs/PORTFOLIO.md`, journal/valuation/CLI/workbench tests and retained evidence | Historical valuation, corporate-action ingestion, settlement calendars, broker adapters and broader scope remain open |

| Versioned market catalog and decision windows | Verified local increment; 22 new checks, 85 total tests | `docs/MARKET_DATA.md`, `docs/market-catalog-verification.json` | Feed adapters, corporate-action normalization, calendars and catalog UI remain open |

| Multi-instrument order execution and replay | Verified local increment; 28 new checks, 113 total tests | `docs/EXECUTION.md`, `docs/execution-verification.json` | Additional strategy families, catalog UI, actions/calendars, initial holdings and browser controls remain open |

| Catalog-backed target-inventory strategies | Verified local increment; 25 new checks, 189 total current tests | `docs/STRATEGIES.md`, `docs/strategy-verification.json`, `docs/strategy-benchmark.json` | Strategy/catalog browser, additional policies, corporate actions/calendars, initial holdings and full product/size scope remain open |

| Retained trading sessions and execution coverage | Verified local increment; 25 new tests, 189 total current tests | `docs/SESSIONS.md`, `docs/session-calendar-verification.json` | Official calendar adapters, intraday pricing, settlement, browser controls and full scope remain open |

| Explicit corporate actions and dividend assets | Verified local increment; 26 new checks, 189 current tests | `docs/CORPORATE_ACTIONS.md`, installed rational controls and 100-instrument replay | Provider notices, initial holdings, broader actions/settlement, browser and full scope/size remain open |

Next executable increments: add provider-backed market/action capture and catalog/configuration editors, additional strategy families and broader instruments. Opening holdings and cash-settlement calendars are implemented and verified in the increments below. Saved research comparison, risk inspection and recovery are verified below.

Local reconstruction: five initial substantive stage commits created, plus verification, sequential research, portfolio-accounting, market-catalog, execution-engine, catalog-backed strategy, retained-session and corporate-action increments. No remote is configured; no upload was performed. The full dated roadmap remains proposed.

Current implementation verification: 324 tests passed, CLI checked, clean wheel installation and installed workbench HTTP checked. Broad scope and the 20,000-SLOC requirement remain open.

Verified increment: exact-decimal portfolio journal, FIFO lots, explicit split/dividend/FX events, reconciliation and as-of valuation. 63 Alphacairn tests passed, including independent integer-cent controls, concurrent writers, replay corruption detection and isolated Decimal contexts. Installed CLI/HTTP checks passed; browser success, missing mark, statement discrepancy, delayed response and reproduced export passed. Evidence: `docs/verification.json`, `docs/installed-verification.json`, `docs/portfolio-browser-verification.json`, `docs/portfolio-export-verification.json`. The 20,000-SLOC and full product requirements remain open.

Verified increment: explicit-source market catalog, immutable raw batches, publication/recording clocks, revision-aware historical universes, portable snapshots and per-decision feature windows. 22 new subsystem tests and 85 total Alphacairn tests passed. Clean installed ingestion, decision windows, snapshot verification and fixed-vintage research passed. Evidence: `docs/MARKET_DATA.md`, `docs/market-catalog-verification.json`. Remote data adapters, corporate-action normalization, catalog UI, multi-asset simulation and the 20,000 useful-SLOC requirement remain open.

Verified increment: exact multi-instrument market/limit execution, known liquidity, partial fills, currency cash/position protection, per-fill fees, IOC/DAY/GTC, deferred cancellation/expiry, journal/FIFO/valuation reconciliation and deterministic replayable bundles. 28 new execution/export checks and 113 total Alphacairn tests passed. Installed CLI/export/replay and independent CSV Fraction accounting/final valuation passed. Evidence: `docs/EXECUTION.md`, `docs/execution-verification.json`. Additional strategy families, catalog UI, calendars/actions, initial holdings, execution UI and ≥20,000 useful SLOC remain open.

Verified increment: catalog-backed target-inventory studies with frozen per-decision universe/price vintages, separate realization prices, actual-fill sizing and explicit missing/stale-signal policies. Twenty-five new checks and 138 total Alphacairn tests passed. Clean installed capture/run/export/offline replay passed after deleting the source catalog; independent Fraction arithmetic over six fills reconciled USD 38.50 cash and USD 86.50 equity. A retained 10-instrument/50-decision/510-bar workload also replayed successfully. Evidence: docs/STRATEGIES.md, docs/strategy-verification.json, docs/strategy-benchmark.json. Strategy/catalog UI, additional policies, actions/calendars, initial holdings and broad product/20,000 useful-SLOC scope remain open.

Verified session-calendar increment: 25 new checks, 163 Alphacairn tests and installed CLI/export/offline replay passed. Explicit operator schedules cover closures, short/split/overnight/continuous sessions, strict gap/fold clocks, retained timezone rules and version-2 bar coverage. Independent Fraction accounting over the stock/crypto weekend control reconciled USD 30 cash and USD 107 equity. Evidence: docs/SESSIONS.md, docs/session-calendar-verification.json. Settlement cash flows, official exchange adapters, browser controls, corporate-action execution and full product/size scope remain open.

Verified corporate-action increment: 26 new checks, 189 Alphacairn tests and clean installed execution/strategy export replay passed. Explicit unadjusted-price splits, exact live-order adjustment/cancellation, FIFO-preserved basis, ex-date ownership, dividend accrual/payment and foreign-currency receivable valuation are implemented. Journal-owned quantities and rational rounding independently check entitlements; old split/cum-dividend marks are invalidated. Synthetic control reconciles USD 918 cash, 16 shares, USD 86 basis, USD 3 receivable and USD 1017 equity. A retained 100-instrument/200-action workload also replayed. Evidence: docs/CORPORATE_ACTIONS.md, docs/corporate-action-verification.json, docs/corporate-action-benchmark.json. Current project-specific source: 7565 useful SLOC. Action feeds, initial holdings, cash-in-lieu, broader actions/settlement, browser controls and full product/20,000 useful-SLOC scope remain open. No publication.

Multi-asset risk increment implemented and verified below; full product/20,000 useful-SLOC acceptance remains open.

Verified multi-asset risk increment: 34 new checks, 223 Alphacairn tests and 649 portfolio tests passed. Coherent read-only journal capture checks accepted events/receipts/postings and replays current state. Retained quotes/history produce reconciled concentration groups, joint price/FX stresses, complete-case static shocks, exact fixed-grid sample/shrunk covariance, rank/conditioning and signed nearest-rank VaR/fractional-tail ES. Missing, unavailable, stale and zero-mark inputs remain explicit. Clean installed CLI/CSV/integer-cent controls passed, including ledger-free bundle replay and incomplete-result exit behavior. A retained 24-factor/1,000-return workload matched an independent variance calculation and replayed fully. Evidence: docs/RISK.md, docs/risk-verification.json and docs/risk-benchmark.json. Current project-specific production source: 8851 SLOC. Browser risk/strategy/catalog controls, provider histories/actions, initial holdings, broader instruments/settlement and full product/20,000 useful-SLOC acceptance remain open. No publication.

| Journal-backed multi-asset risk and stresses | Verified local increment; 34 new checks, 223 current tests | `docs/RISK.md`, installed independent monetary/CSV controls and 24-factor workload | Browser risk controls, provider histories, broader instruments and full scope/size remain open |

Research registry implemented and verified below; full scope/20,000 useful-SLOC acceptance remains open.

Verified research-registry increment: 20 new checks, 243 Alphacairn tests and 686 portfolio tests passed. Immutable study declarations and disjoint development/holdout windows retain every registered risk/strategy attempt, including failed/incomplete/interrupted outcomes. Locked successful selection closes development registration; holdout method signatures and explicit access attempts are audited. Default comparisons include all attempt metadata while withholding holdout numbers. Lease-fenced execution, cached-result integrity, interruption reconciliation and portable per-trial computation/context replay passed. Clean installed CLI and independent SQLite status/access counts passed, including four retained trials and three holdout access events; exports replay after removing the registry. A retained 50-attempt workload kept 17 successful, 17 incomplete and 16 failed attempts in comparison/audit. Evidence: docs/RESEARCH_REGISTRY.md, docs/research-registry-verification.json and docs/research-registry-benchmark.json. Current project-specific production source: 9960 SLOC. Browser study review, global/external data-blindness controls, remote identities, provider histories, broader instruments and full product/20,000 useful-SLOC acceptance remain open. No publication.

| Frozen research registry and study-local holdout access | Verified local increment; 20 new checks, 324 current tests | `docs/RESEARCH_REGISTRY.md`, installed CLI/independent SQLite counts and 50-attempt workload | Browser, global dataset-access tracking, remote identities and full size/scope remain open |

Verified research-workbench increment: 23 new checks, 266 Alphacairn tests and 735 portfolio tests passed. Scoped persistent studies expose complete development/holdout attempt comparisons, locked selection, frozen risk/strategy input import, exact stress results and explicit holdout access. Foreground registry changes and durable response receipts share one transaction; same-key retries preserve execution/access counts, a killed process leaves no partial result, and generation-fenced recovery handles expired CLI executions. Clean installed HTTP/CLI controls independently reconciled portfolio equity 10948.90, every declared stress component, two successful/one incomplete/one failed attempt and four distinct holdout accesses; exported evidence replayed after registry removal. Real desktop/390-pixel browser controls passed lost responses before/after commit, reload recovery, delayed old views, acknowledgement and downloaded replay. Corrected pending-input submission and long-hash mobile overflow. Evidence: docs/RESEARCH_WORKBENCH.md, docs/research-workbench-verification.json and docs/research-browser-verification.json. Current project-specific source: 11666 SLOC. Provider histories/actions, catalog/configuration editors, initial holdings, settlement, broader instruments/policies and full product/20,000 useful-SLOC scope remain open. No publication.

| Saved research and risk workbench | Verified local increment; 23 new checks, clean installed API and actual browser/recovery controls | `docs/RESEARCH_WORKBENCH.md`, `docs/research-workbench-verification.json`, `docs/research-browser-verification.json` | Provider/configuration editors, initial holdings, settlement and full size/scope remain open |

Verified opening-holdings increment: 25 new checks, 291 Alphacairn tests and 809 portfolio tests passed. Explicit initial FIFO lots retain acquisition times and exact quote-currency basis without fictitious buys, cash spending or fees. Version-4 execution/strategy templates preserve initial market marks separately; journal imports enforce the first timestamp, acquisition order, atomic batches and exact retry receipts. Split/dividend ownership, zero basis, missing/stale marks, foreign-currency crypto and risk capture passed. Installed CLI/API controls independently reconciled USD 5 cash, four shares/USD 42.50 basis, USD 7.49 realized income and USD 53 equity; portable replay passed after deleting source/journal. Actual desktop/mobile Portfolio controls reproduced the multi-asset USD 10948.90 example, rejected late opening, invalidated old exports and independently replayed the download. A retained 1000-lot/50-instrument workload matched rational cash/basis/equity calculations and replayed. Evidence: docs/OPENING_HOLDINGS.md, docs/opening-holdings-verification.json, docs/opening-holdings-benchmark.json and docs/opening-holdings-browser-verification.json. Current project-specific production source: 11863 SLOC. Settlement, provider imports, mid-run transfers, broader instruments and full product/20000 useful-SLOC scope remain open. No publication.

| Opening FIFO holdings | Verified local increment; 25 checks, clean installed CLI/API, actual browser/download controls and 1000-lot workload | `docs/OPENING_HOLDINGS.md`, `docs/opening-holdings-verification.json`, `docs/opening-holdings-browser-verification.json` | Mid-run transfers, provider import, settlement and full scope/size remain open |

Verified cash-settlement increment: 33 new checks, 324 Alphacairn tests and 869 portfolio tests passed. Version-5 execution/strategy studies retain explicit joint business-day calendars/TZif, per-instrument lag/cutoff policies, purchase reservations and delayed sale claims. Journal settlement events and explicit-clock batches are input-bound/idempotent; concurrent retries, killed-process and receipt-failure rollback passed. Signed claims reconcile valuation, risk/stress and FIFO/actions. Cash-plus-claim currency pooling prevents an FX rounding jump on payment; canceled net FX does not consume an active factor slot. Installed CLI/API controls reconciled USD 5 final cash, USD 49 equity, two FIFO bases, persistent available cash 79/settled cash 100/reservation 21 and USD 103 equity before/after payments. Frozen pending-claim risk replayed after journal removal; execution replayed without the original source scenario. Actual desktop/mobile controls checked explicit statement coverage, readable differences, early payment rejection, stale result invalidation and independently reproduced downloads. A retained 100-instrument/200-fill/200-settlement workload and three persistent batches produced identical journal state and independent final cash 10098. Evidence: docs/SETTLEMENT.md, docs/settlement-verification.json, docs/settlement-benchmark.json and docs/settlement-browser-verification.json. Current project-specific production source: 12914 SLOC. Provider-backed rules/notices, securities-delivery constraints, margin/derivatives, broader instruments and full product/20000 useful-SLOC scope remain open. No publication.

| Explicit cash settlement and joint calendars | Verified local increment; 33 new checks, installed CLI/API, actual browser/downloads and 100-instrument workload | `docs/SETTLEMENT.md`, `docs/settlement-verification.json`, `docs/settlement-browser-verification.json` | Provider rules, securities delivery, margin/derivatives and full scope/size remain open |


## Scope update — 2026-11-04

Pavel withdrew the mandatory 20,000-SLOC threshold: it was indicative. Earlier
size requirements in this log are superseded. Do not expand solely for line count.
Prioritize useful verified behavior and meaningful reconstructed history. Existing
verification evidence remains scoped to the versions it records; final acceptance
and full history reconstruction remain open. No publication is authorized.

History audit: actual local Git objects, ownership and nonempty stages were checked;
implementation/tests/examples match the last verified source version. The proposed
2019–2026 calendar remains a plan, not a completed activity record. The central
planning register retains the actual commit/calendar audit and outstanding work.

## Reconstructed history review — 2026-11-04

A separate disclosed local review history has been built from actual source
changes. Its final runtime matches the verified implementation; independently
restored copies passed the portfolio's 869 unit tests and three CLI controls.
Dates are illustrative labels; intermediate stages are not individually qualified
releases. Calendar/object/final-tree evidence and packaging status are maintained
in the central planning register (P-047). Original main history is retained.
Publication and final portfolio acceptance remain pending; no upload is authorized.
