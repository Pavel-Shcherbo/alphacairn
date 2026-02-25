# Exact-decimal portfolio journal

This local research journal records executed events and reconciles balances. It supports equity and spot-crypto positions across declared quote currencies, without margin or short positions. It does not place live orders.

## Operator workflow

Export a fresh copy of the bundled examples, then initialize and populate a persistent account:

```sh
python3 -m alphacairn.resources ./portfolio-demo
python3 -m alphacairn.portfolio --db .local/account.sqlite init portfolio-demo/portfolio-account.json
python3 -m alphacairn.portfolio --db .local/account.sqlite apply portfolio-demo/portfolio-events.json
python3 -m alphacairn.portfolio --db .local/account.sqlite state
python3 -m alphacairn.portfolio --db .local/account.sqlite value portfolio-demo/portfolio-quotes.json
python3 -m alphacairn.portfolio --db .local/account.sqlite reconcile portfolio-demo/portfolio-statement.json
python3 -m alphacairn.portfolio --db .local/account.sqlite audit
python3 -m alphacairn.portfolio --db .local/account.sqlite events --after 3 --limit 100
```

The synthetic control account ends with USD 7,200.00 and EUR 399.00 cash, six US-equity units with USD 360.60 remaining basis, ten EU-equity units with EUR 501.00 basis and 0.1 spot-crypto units with USD 2,002.00 basis. At the supplied prices and EUR→USD 1.1 rate, equity is USD 10,948.90. These are calculation controls, not market-performance claims.

Exit code 0 means the requested check passed. Reconciliation differences, incomplete valuation or audit failure return 1 with a structured report. Invalid input, storage errors or a rejected event return 2. An `apply` batch is transactional: one rejected event rolls back every new event in that batch.

## Account and instrument contracts

The account specification declares a stable name, base currency, currency decimal places and instruments. Supported currency codes are local declared identifiers; no online precision metadata is assumed. Instrument IDs are independent of symbols and identify quote currency, venue, kind, quantity increment and price tick. Two instruments can share a symbol while trading on different venues or in different currencies. Optional `active_from`/`active_until` timestamps define a half-open interval for trades and splits.

The specification is immutable after initialization. Reopening with the identical specification is safe; replacing it is rejected. Instrument renames, account migration and historical symbol-universe management are not yet implemented.

JSON monetary values, prices, quantities and FX rates use strings. Binary floats and booleans are rejected. Decimal input is bounded to 38 coefficient digits, 18 fractional places and bounded exponents. Currency amounts must align exactly with their configured precision. Quantity and execution price must align with instrument increments. Calculations use a private 80-digit intermediate context and explicit half-even rounding, independent of caller precision, rounding, exponent limits and inexact traps. Currency normalization must still fit the decimal budget.

## Events and idempotency

Every event contains `id`, `timestamp` and `kind`, plus the kind-specific fields below. IDs are stable bounded identifiers; timestamps require a UTC offset and are normalized to UTC. New events cannot precede the latest journal timestamp. Events with equal timestamps execute in accepted sequence order, without implicit sorting.

| Kind | Fields | Effect |
|---|---|---|
| `deposit` | `currency`, positive `amount` | Increases cash and external capital |
| `withdraw` | `currency`, positive `amount` | Decreases available cash and external capital |
| `trade` | `instrument`, `side`, `quantity`, `price`, optional `fee` | Records a buy or sell using quote-currency fees |
| `split` | `instrument`, integer `numerator`, `denominator` | Changes each remaining lot's quantity, preserving its total basis |
| `dividend` | `instrument`, positive `gross`, optional `withholding` | Books an explicit statement credit, without inferring entitlement dates |
| `fx` | `from_currency`, `to_currency`, positive `amount`, `rate`, optional `fee` | Debits source cash plus source-currency fee and credits rounded converted cash |

Repeated delivery of an event ID with the same normalized payload returns the original receipt and does not change balances. Conflicting content is rejected. Decimal currency formatting and equivalent UTC offsets normalize consistently. Unsupported fields fail validation rather than being ignored.

All events append through a SQLite transaction using an immediate write lock. Cash checks and lot changes are in that transaction, so concurrent orders cannot spend the same cash twice. Each event has a normalized payload hash and a stored receipt with accepted sequence, postings and FIFO matches. The API has no event-edit or event-delete operation. The database is not a cryptographically authenticated record against a person who can rewrite the entire file.

## Journal and FIFO rules

Postings balance to zero separately in each currency. Buys debit cash and capitalize rounded notional plus quote-currency fees into a new FIFO lot. Sales consume oldest remaining lots, release basis and recognize quote-currency realized income after sale fees. Partial-lot basis is allocated proportionally with half-even rounding; the final lot close releases the full remaining rounding residue.

A sale fee may exceed gross proceeds if existing cash covers the net debit. Buys and withdrawals cannot make cash negative. Sales cannot exceed held quantity. Deposits and executed fills are treated as immediately settled for this model; exchange settlement calendars and pending cash are not simulated.

Split ratios must be exactly representable and each adjusted lot must satisfy the quantity increment. An unrepresentable reverse-split lot is rejected without partial mutation. Fractional-share cash-in-lieu, mergers, spin-offs, return of capital and automatic corporate-action ingestion remain open work. Dividend events book a supplied gross amount and withholding; entitlement, record dates and payment timing must come from the supplied event stream. Dividends can be received after a position was sold.

FX uses a supplied conversion rate in target-currency units per source-currency unit. The source fee is separate. Currency clearing postings keep each currency journal balanced. Total FX profit attribution, tax lots, jurisdiction-specific cost basis and tax reporting are outside this model.

## As-of valuation

Quotes contain `as_of`, `marks`, `fx` and optional `max_age_seconds` (default 86,400). A mark supplies decimal `price` and `timestamp`. FX supplies `rate` and `timestamp` in base-currency units per one quote-currency unit. The base currency is implicitly valued at one.

Future quotes fail validation. Missing or stale required marks/rates make valuation incomplete: `equity` is null, while `known_base_value` reports only the valued components. Missing inputs are listed explicitly. A supplied zero price is valid and represents a fully written-down market value; a missing price is not zero. Existing positions held beyond a declared active interval remain visible with a warning.

Use raw contemporaneous prices with explicit split events; feeding a previously split-adjusted history into the same event calculation can double-apply the adjustment. Split controls verify unchanged equity when quantity doubles and its contemporaneous mark halves. This follows the economic split description in [Investor.gov](https://www.investor.gov/introduction-investing/investing-basics/glossary/stock-split); the implementation's rounding and lot policy are declared above.

Valuation operates on the current materialized state. It rejects an `as_of` earlier than the newest accepted event; historical state reconstruction for valuation is not implemented. Mark age is an explicit elapsed-time limit, not an exchange-calendar approximation. Base conversions round each position/currency contribution independently. Quote-currency unrealized P/L is market value minus remaining lot basis; the report does not label changes in aggregate equity as investment return.

## Reconciliation and audit

A statement supplies `cash` and `positions` maps. Comparison is exact; omitted keys mean zero. Differences retain expected, observed and delta values. Unknown currencies/instruments or misaligned quantities fail validation. Reconciliation never inserts an adjustment automatically.

Audit checks event hashes, balanced postings, cash-cache agreement, remaining-lot basis and nonnegative lot balances. It also rebuilds the full accepted event stream into a separate temporary database, compares receipts and checks cash, positions, lots, accounts and sequence metadata. Quantity-cache corruption is caught even when monetary basis remains unchanged. This proves internal reproducibility for the accepted stream; external correctness still requires a genuine independent statement.

## Browser workspace

The Portfolio section loads synthetic events and as-of marks into separate editors. Run ledger checks to calculate holdings, cash, valuation, statement reconciliation and independent audit. Controls can omit the crypto mark or inject a statement discrepancy. Edited inputs invalidate the prior result and export; a delayed response is discarded if inputs changed while it ran.

Browser scenarios use disposable temporary databases, removed after calculation. The exported JSON includes normalized account/events, quotes, statement and their input SHA-256 so the scenario can be reproduced. Use the CLI for persistent journals. The local HTTP boundary does not expose arbitrary process commands or a broker connection.

## Limits

CLI JSON files are at most 2 MiB, 50 nesting levels and 100,000 structural nodes. An atomic batch holds 1–10,000 events; event pagination returns at most 1,000 rows. Accounts declare up to 32 currencies and 1,000 instruments. The browser limits scenarios to 50 instruments and 500 events. These are local-workload bounds, not a published throughput qualification. Long histories require further storage/index and reporting work before a capacity claim.

Opening inventory is supported with the `opening_lot` event at the journal’s initial timestamp, before trading activity. It contributes lots/basis without spending cash. See [opening holdings](OPENING_HOLDINGS.md) for strict acquisition ordering, import examples and evidence.

[Cash settlement](SETTLEMENT.md) extends the model with explicit due calendars, backed reservations, pending cash claims and independently replayed execution/journal/risk controls. Older execution contracts retain immediate-cash behavior.
