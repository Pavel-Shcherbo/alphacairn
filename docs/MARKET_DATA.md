# Versioned local market data

The catalog separates an observation's event time, source-declared publication time and actual local ingestion time. It retains original input bytes in SQLite, hashes the raw batch and normalized observations, and appends revisions. It never fetches exchange data or places an order. All bundled prices and memberships are synthetic controls.

## A complete local workflow

Run from this checkout, or export examples with `python3 -m alphacairn.resources demo` and replace `examples/` below with `demo/`:

```sh
python3 -m alphacairn.market_cli --database market.sqlite init
python3 -m alphacairn.market_cli --database market.sqlite ingest synthetic bar examples/market-bars.json --request-key bars-1
python3 -m alphacairn.market_cli --database market.sqlite ingest synthetic membership examples/market-universe.json --request-key universe-1
python3 -m alphacairn.market_cli --database market.sqlite snapshot examples/market-query.json --output vintage.json
python3 -m alphacairn.market_cli verify-snapshot vintage.json
python3 -m alphacairn.market_cli --database market.sqlite decision-windows examples/market-decisions.json
python3 -m alphacairn.market_cli --database market.sqlite history synthetic bar DEMO-A
python3 -m alphacairn.market_cli --database market.sqlite audit
python3 -m alphacairn.research risk --market-snapshot vintage.json --lookback 1
```

The first two decision windows have January 2 close 10 and January 3 close 20. At the second decision, their mean is 15. A revision published on January 6 changes January 2 to 30; the third window then has mean 25. The revision cannot change the first two decision windows. DELISTED-DEMO remains a member in the early windows, with an explicit not-ready feature because it has no price observations; after its exclusive January 4 membership end, it is absent. This checks selection behavior, not exchange coverage or a profitable trading strategy.

Commands print JSON. Input/storage failures exit 2; an incomplete or failed audit exits 1. Read operations require an existing initialized catalog and do not create a missing database. `verify-snapshot` operates offline and does not open the database. Snapshot publication is atomic and create-only; existing files and symbolic links are never overwritten.

## Observation contract

An input is one JSON array, at most 16 MiB and 100,000 observations. Duplicate JSON keys, duplicate observation/publication pairs, unknown fields and invalid numbers are rejected before a transaction starts. A failed batch cannot leave partial rows or consume its idempotency key.

A daily bar has exactly these fields:

- `instrument`: stable identifier; symbols are not automatically resolved.
- `session`: YYYY-MM-DD session label supplied by the source.
- `opened_at`, `closed_at`, `published_at`: timezone-aware ISO instants normalized to UTC with microseconds. Opening precedes closing; closing cannot follow publication.
- `status`: `active` or `retracted`.
- `open`, `high`, `low`, `close`, `volume`: exact decimal text or integers. Prices are positive; volume is nonnegative; low/high enclose opening and closing. A retracted bar has null values in all five numeric fields.

Decimal input uses the portfolio's bounded finite parser: at most 38 significant digits and exponent magnitude 18. Floating-point input is rejected. The catalog preserves exact decimal strings; the existing descriptive analytics explicitly convert prices to floating point.

A membership has exactly `instrument`, `universe`, `valid_from`, `valid_until`, `published_at`, `status`. Membership intervals are half-open: valid from the first session, absent on `valid_until`; a null end is open-ended. Future membership announcements are permitted. Corrections use the same instrument/universe/start identity with a later publication time. Retractions remove that interval. An overlapping selected interval for the same instrument raises an error rather than silently duplicating or choosing a member.

## Revision and source identity

A bar identity is `(source, instrument, session)`; this is a daily-bar store, not an arbitrary intraday interval store. A membership identity adds universe and interval start. A new publication time appends a revision. Conflicting values at the same identity and publication time are rejected. Identical observations in another raw batch refer to their first indexed batch and retain their first local recording time.

Each import has an explicit source and request key. Repeating identical source/kind/raw input returns the original batch; reusing a request key for different bytes fails. Whitespace changes produce another raw batch, while identical normalized revisions remain deduplicated. Different sources are never silently merged or ranked. Source identifiers are logical names, not authenticated provider identities.

## Information clocks

Every query chooses one clock:

- `published`: accept revisions whose source-declared publication time is no later than `known_at`. This can reconstruct a claimed historical provider timeline from a file loaded today. It does not prove the data existed or was available then.
- `recorded`: additionally require the batch's actual local ingestion time no later than `known_at`. A file loaded today cannot become historically available merely by containing an old publication timestamp. Future-dated publication still prevents selection.

The latest eligible revision is selected before filtering retractions or interval end dates. Filtering active values first would incorrectly bring back an obsolete value after withdrawal. Daily bar queries also check that the bar closed by the knowledge cutoff. Session labels and decision sessions are explicit source inputs; no exchange timezone, holiday, auction or settlement schedule is inferred.

Single snapshots select one data vintage at one cutoff. A backtest over that vintage may use revisions published after an earlier historical decision. Research output retains this limitation, the original snapshot-file hash, snapshot identity and query. For per-decision eligibility, use `decision-windows`: each decision selects its own universe and trailing bars. All windows share one SQLite read transaction, so concurrent ingestion cannot mix catalog states across one report. The output is a feature panel, not a simulated execution report.

Each feature retains its selected session list, observation hashes, input snapshot hash, readiness, last close and trailing mean. Insufficient histories remain explicitly not ready; there is no interpolation, forward fill, automatic substitution, or omission of members with missing bars. The mean uses the private 80-digit decimal context. Every window can include at most 100 instruments; each report at most 100 increasing decision instants and 100,000 selected-history work units, with lookbacks from 1 to 1,000 observations. Gaps are observation gaps, not inferred trading sessions.

## Storage and verification

SQLite transactions serialize writers; WAL read transactions provide a coherent view during concurrent ingestion. Initialization uses schema version 1 and rejects unknown versions. The local database is owner-readable/writable when created. This is a local logical namespace, without server authentication or access-control roles.

Snapshots retain the query, selected normalized records, original batch IDs, recording times, observation hashes and one canonical-content SHA-256. Offline verification checks types, hashes, uniqueness, temporal eligibility, status and query membership. It does not certify completeness against an unavailable catalog, provider authenticity, or possession of the original raw batch. Snapshots cannot exceed 16 MiB for file export. Hashes detect changed bytes; they are not signatures.

`audit` checks original bytes, normalized batch identities, indexed values, batch ownership and SQLite foreign keys in one read view. A complete audit also detects missing or extra indexed revisions. It is bounded to 1,000 batches, 100,000 raw observations and 64 MiB of raw bytes per call; a narrower `--limit` can be supplied. A truncated audit has `complete: false`, `passed: false`; it is never reported as a successful full audit. Batch listings have explicit cursors; revision history reports whether its bounded result is complete.

## Remaining work

No paid feed or remote adapter, provider signature, exchange calendar, automatic split/dividend adjustment, symbol mapping, authenticated multi-user service or comprehensive exchange universe is implemented here. The existing portfolio journal supports explicit actions; this market catalog does not automatically apply them. Raw-price feature means across an unmodeled corporate action can be misleading. Browser management of this catalog and multi-asset execution simulation remain open. Full product scope and the 20,000 useful-SLOC acceptance remain open.
