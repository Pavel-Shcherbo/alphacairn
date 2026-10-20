# Architecture

## Current implementation

CSV validation creates dated bars. The simulator derives a target from already observed closes, trades at the following bar's open and marks equity at that bar's close. The web adapter and CLI use the same calculation. A report retains the source hash and parameters. The same costs are applied to the baseline. The workbench runs bounded local studies and has no brokerage or exchange order endpoint.

## Verification

Signal timing, unchanged historical decisions after appending future observations, control-case fees and drawdowns, invalid prices, duplicate/out-of-order dates and invalid cost parameters.

## Local HTTP boundary

The workbench binds to loopback, validates the Host header, rejects foreign
Origin values and requires a custom header for state-changing requests. Static
files are served from an explicit allowlist. The ordinary evaluation route limits request bodies to 1 MiB; the saved-research route permits up to 8 MiB.
These measures support a local development tool; there is no production identity,
authorization or organization model yet.

## Remaining boundaries

Official market/provider integrations, live brokerage, margin, shorting and
additional instrument families are outside the current local implementation.
Corporate actions, retained session calendars and multi-asset execution are
implemented as described below; source data remains explicitly supplied.

## Portfolio journal

`instruments` declares stable account and instrument identities. `money` supplies a private exact-decimal arithmetic context, bounded values, increments and explicit currency rounding. `ledger` appends normalized idempotent events, applies FIFO lots and balanced postings under one SQLite write transaction, and reconciles against independent supplied balances. Its audit rebuilds accepted events into a separate database and compares receipts and materialized state.

`valuation` applies explicit as-of marks and FX rates without treating missing prices as zero. `portfolio` exposes persistent operator commands; `portfolio_web` runs bounded disposable scenarios with exportable normalized inputs. The browser invalidates obsolete results on input edits and discards delayed responses. Details and limits are specified in PORTFOLIO.md.

## Market data clocks

`market_model` validates bounded exact-decimal daily observations, explicit publication clocks, interval memberships and portable snapshot identity. `market_store` retains original batches and immutable revisions under SQLite transactions; a consistent read view spans related queries during concurrent ingestion. `market_research` exports and verifies snapshots and rebuilds each decision window from its eligible revisions and membership. `market_cli` exposes local operations; the research CLI accepts a verified fixed-vintage snapshot and retains its distinct timing assumptions. No remote market source or brokerage connection is configured. See MARKET_DATA.md.

## Multi-instrument execution

`execution_model` validates explicit bar clocks, pre-open liquidity knowledge, account/cost contracts and ordered instructions. `execution_book` allocates simultaneous cross-instrument fills by command priority under cash, holding, lot and shared-liquidity bounds. `execution_money` provides exact affordability and marked values; `execution_engine` processes expiry/close/command/open phases and independently reconciles funding/fills through the existing portfolio journal and valuation. `execution_export` publishes create-only deterministic bundles and verifies them by re-running the scenario; `execution` is the local operator CLI. Strategy generation is a separate input-capture layer described below; live brokerage is absent. See EXECUTION.md.


## Decision-time studies and retained sessions

`strategy_inputs` freezes each decision's eligible universe and price revisions
separately from realization bars. `strategy_engine` sizes target-inventory orders
from actual prior fills and applies the declared missing/stale signal policy.
`strategy_bundle` retains enough inputs for source-catalog-free replay. This
separation prevents execution prices from silently becoming decision features.
`session_calendar` and `session_zones` retain operator calendars and TZif rules;
`session_model` checks explicit bar coverage, split/overnight sessions and local
clock ambiguity. See [strategies](STRATEGIES.md) and [sessions](SESSIONS.md).

## Corporate actions, inventory and settlement

Declared unadjusted-price splits preserve FIFO basis and adjust/cancel working
orders explicitly. Dividend ownership is fixed at the declared entitlement time;
receivables and later payments remain separate events. Opening holdings retain
acquisition dates and book basis independently of market marks. The execution
engine and persistent journal reconcile the same quantities, cash and events.

`settlement_clock` resolves per-instrument joint-calendar cash due times.
`settlement_accounts` and `settlement_book` distinguish settled cash, purchase
reservations and signed pending claims. `settlement_service` commits idempotent
explicit-clock payment batches. Positions move at trade time; securities-delivery
restrictions and borrowing are not modeled. Cash-plus-claim currency pooling
avoids a rounding discontinuity when a claim becomes cash. See
[corporate actions](CORPORATE_ACTIONS.md), [opening holdings](OPENING_HOLDINGS.md)
and [cash settlement](SETTLEMENT.md).

## Risk and saved research

`risk_inputs` freezes a coherent journal capture with quotes, history and declared
stress assumptions. `risk_positions` reconciles exposures and signed claims;
`risk_matrix` and `risk_tail` calculate exact bounded descriptive diagnostics.
Missing/stale inputs produce explicit incomplete outcomes. `risk_bundle` replays
without the source journal; a covariance or tail estimate is not a forecast.

`studies` retains study-local windows, every registered attempt, locked selections
and explicit holdout accesses. `research_desk` runs scoped frozen inputs and
commits results with durable response receipts. The saved-experiments page rejects
stale responses and recovers a lost reply using the original request identity.
Study-local access tracking does not prove global data blindness or authenticate
remote users. See [risk](RISK.md), [registry](RESEARCH_REGISTRY.md) and
[research workbench](RESEARCH_WORKBENCH.md).
