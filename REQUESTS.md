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

Implemented increment: 63 current tests passed; CLI and installed workbench entry points checked in a disposable clean environment. Current project-specific production source: 3278 SLOC, below 20,000. No publication.

Verified increment: exact-decimal portfolio journal, FIFO lots, explicit split/dividend/FX events, reconciliation and as-of valuation. 63 Alphacairn tests passed, including independent integer-cent controls, concurrent writers, replay corruption detection and isolated Decimal contexts. Installed CLI/HTTP checks passed; browser success, missing mark, statement discrepancy, delayed response and reproduced export passed. Evidence: `docs/verification.json`, `docs/installed-verification.json`, `docs/portfolio-browser-verification.json`, `docs/portfolio-export-verification.json`. The 20,000-SLOC and full product requirements remain open.
