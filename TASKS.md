# Tasks

Updated: 2026-11-04. Actual status only; historical roadmap rows remain proposed.

| Task | Status | Evidence | Remaining work |
|---|---|---|---|
| Core domain path | Implemented; 22 current tests passed | `alphacairn/`, `tests/` | Expand adversarial coverage as the model grows |
| Local CLI | Implemented; CLI end-to-end checks passed | `alphacairn/__main__.py`, `examples/` | Retained in the local verification evidence |
| Local workbench | Implemented; local HTTP and reviewed browser flows passed | `alphacairn/web.py`, `alphacairn/static/` | Retain checks as new screens and flows are added |
| Broad product scope | Planned | `docs/PRODUCT_SCOPE.md` | Most platform subsystems require implementation |
| Weekly reconstruction plan | Written | `docs/proposed-weekly-roadmap.csv` | Proposed commit counts are not actual commits |
| Publication | Waiting on Pavel | Current request: do not upload without Pavel | No push or hosted deployment |
| Production implementation ≥20,000 useful SLOC | Not achieved | 1840 project-specific SLOC measured; not achieved | Implement and verify the broad subsystem scope without padding |
| Risk analytics | Implemented; control-case tests passed | `alphacairn/analytics.py`, `tests/test_analytics.py` | Document assumptions and expose comparisons in the workbench |
| Walk-forward studies | Implemented; timing and cash-reconciliation tests passed | `alphacairn/walkforward.py`, `tests/test_walkforward.py` | Browser workflow and retained CLI evidence in progress |
| Installable local package | Verified from a clean environment outside the source tree | `docs/installed-verification.json`, `_build.py`, `MANIFEST.in` | Cross-version/platform qualification remains open |


Next executable increment: Introduce instrument and data-version contracts, then add hand-checked corporate actions and historical-universe fixtures before multi-asset evaluation.

Local reconstruction: five initial substantive stage commits created, plus the current verification record. No remote is configured; no upload was performed. The full dated roadmap remains proposed.

Current implementation verification: 22 tests passed, CLI checked, clean wheel installation and installed workbench HTTP checked. Broad scope and the 20,000-SLOC requirement remain open.
