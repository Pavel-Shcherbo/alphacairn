# Alphacairn guides

Begin with the synthetic example. Keep market availability, execution assumptions and accounting inputs explicit.

[Install and run](../README.md#run-the-workbench) · [Architecture](ARCHITECTURE.md) · [Verified scope](VERIFICATION.md)

## Choose a task

| Task | Guide | What to expect |
|---|---|---|
| Reconcile a portfolio journal | [Portfolio](PORTFOLIO.md) | Track exact cash, FIFO lots, commissions and portable replay. |
| Retain market vintages | [Market Data](MARKET_DATA.md) | Separate observation time, publication time and decision-time eligibility. |
| Run a catalog-backed strategy | [Strategies](STRATEGIES.md) | Capture decision inputs and reconcile simulated target orders through accounting. |
| Inspect execution assumptions | [Execution](EXECUTION.md) | Review liquidity, partial fills, costs and independently replayed fills. |
| Apply splits and dividends | [Corporate Actions](CORPORATE_ACTIONS.md) | Inspect ownership, entitlement and action timing. |
| Start with existing positions | [Opening Holdings](OPENING_HOLDINGS.md) | Retain acquisition times and exact basis without inventing purchase events. |
| Model cash settlement | [Settlement](SETTLEMENT.md) | Keep trade-date holdings separate from available settled cash. |
| Retain a simulation session | [Sessions](SESSIONS.md) | Resume exact event histories and verify exported results. |
| Compare sequential research | [Research](RESEARCH.md) | Use train/test boundaries and explicit holdout assumptions. |
| Register study attempts | [Research Registry](RESEARCH_REGISTRY.md) | Preserve attempt inputs, selection and review history. |
| Inspect saved research in the browser | [Research Workbench](RESEARCH_WORKBENCH.md) | Compare attempts, acknowledge operations and replay exported evidence. |
| Review portfolio risk | [Risk](RISK.md) | Read explicit risk inputs, policies and scenario limitations. |

## Scope and evidence

The [verification record](VERIFICATION.md) describes the actual platform, Python-version and installed-package checks. Subsystem guides record their own increment-specific evidence; an old test total is not a current total.

[Product scope](PRODUCT_SCOPE.md) and the weekly roadmap include future ideas. They are not a checklist of completed features. Earlier Git dates are explicitly reconstructed; see the [history note](../README.md#history-note).

[Contributing](../CONTRIBUTING.md) explains local checks and how to report a reproducible problem.
