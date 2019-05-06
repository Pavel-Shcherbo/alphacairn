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

Introduce instrument and data-version contracts, then add hand-checked corporate actions and historical-universe fixtures before multi-asset evaluation.
