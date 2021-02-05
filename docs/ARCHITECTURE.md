# Architecture

## Current implementation

CSV validation creates dated bars. The simulator derives a target from already observed closes, trades at the following bar's open and marks equity at that bar's close. The web adapter and CLI use the same calculation. A report retains the source hash and parameters. The same costs are applied to the baseline. The workbench runs bounded local studies and has no brokerage or exchange order endpoint.

## Verification

Signal timing, unchanged historical decisions after appending future observations, control-case fees and drawdowns, invalid prices, duplicate/out-of-order dates and invalid cost parameters.

## Local HTTP boundary

The workbench binds to loopback, validates the Host header, rejects foreign
Origin values and requires a custom header for state-changing requests. Static
files are served from an explicit allowlist. Request bodies are limited to 1 MiB.
These measures support a local development tool; there is no production identity,
authorization or organization model yet.

## Next architectural increment

Expose the market catalog in management views, then add corporate-action-aware prices and session calendars before multi-asset execution evaluation.

## Portfolio journal

`instruments` declares stable account and instrument identities. `money` supplies a private exact-decimal arithmetic context, bounded values, increments and explicit currency rounding. `ledger` appends normalized idempotent events, applies FIFO lots and balanced postings under one SQLite write transaction, and reconciles against independent supplied balances. Its audit rebuilds accepted events into a separate database and compares receipts and materialized state.

`valuation` applies explicit as-of marks and FX rates without treating missing prices as zero. `portfolio` exposes persistent operator commands; `portfolio_web` runs bounded disposable scenarios with exportable normalized inputs. The browser invalidates obsolete results on input edits and discards delayed responses. Details and limits are specified in PORTFOLIO.md.

## Market data clocks

`market_model` validates bounded exact-decimal daily observations, explicit publication clocks, interval memberships and portable snapshot identity. `market_store` retains original batches and immutable revisions under SQLite transactions; a consistent read view spans related queries during concurrent ingestion. `market_research` exports and verifies snapshots and rebuilds each decision window from its eligible revisions and membership. `market_cli` exposes local operations; the research CLI accepts a verified fixed-vintage snapshot and retains its distinct timing assumptions. No remote market source or brokerage connection is configured. See MARKET_DATA.md.
