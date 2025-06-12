# Opening holdings and FIFO basis

Version-4 execution scenarios and the persistent portfolio journal can start with
held equity/spot-crypto lots. Opening inventory does not produce a simulated buy,
spend cash, consume bar liquidity or incur execution fees. Its original cost basis
remains available for FIFO sales, splits, dividend ownership and risk capture.

## Run a complete synthetic control

```sh
python3 -m alphacairn.resources ./opening-demo
python3 -m alphacairn.execution run opening-demo/opening-execution.json --output ./opening-study
python3 -m alphacairn.execution verify ./opening-study
```

This example starts with five shares: two with USD 13.01 basis acquired in June,
and three with USD 27.00 basis acquired in December. The opening mark is USD 8,
so initial market equity is USD 40.00, distinct from USD 40.01 book basis.
There is no initial cash. A sale of three shares at USD 10, followed by a purchase
of two at USD 12, incurs USD 0.50 per fill. It ends with USD 5.00 cash, four shares,
USD 42.50 remaining basis, USD 7.49 realized income and USD 53.00 marked equity.
Those are synthetic calculation controls, not a return or broker-data claim.

## Execution declaration

Version 4 retains every version-3 calendar/corporate-action field and additionally
requires `initial_lots` and `initial_marks`, including explicit empty lists when
there are none. Version 1–3 contracts remain unchanged and reject these fields.

```json
{
  "initial_lots": [
    {
      "id": "older-lot",
      "instrument": "A",
      "quantity": "2",
      "basis": "13.01",
      "acquired_at": "2019-06-01T00:00:00Z"
    }
  ],
  "initial_marks": [
    {"instrument": "A", "at": "2020-01-01T00:00:00Z", "price": "8"}
  ]
}
```

`basis` is the total quote-currency basis of that lot, including any historical
costs already attributed by the operator. It is not a unit price. Basis must be
nonnegative and exact at the declared currency precision; explicit zero is
supported. Quantity must be positive and aligned with the instrument increment.
Dates require explicit UTC offsets, acquisition cannot follow the opening clock,
and the instrument must be active at acquisition and opening.

Up to 1,000 lots are supported, with unique IDs of at most 80 characters. The
compiler sorts by instrument, acquisition instant and ID to establish stable
FIFO order. A generated journal event adds the `simopen-` prefix. Subsequent
simulated purchases follow all opening lots. Equal-date lots use that explicit
ID ordering, rather than an inferred broker ordering.

There can be at most one opening mark per held instrument. Its timestamp cannot
follow the scenario start. Missing or stale marks/FX make opening valuation
incomplete; cost basis is never substituted for a market quote. Supplied FX at the
start is used by the existing clock. A split or dividend ex event at the same
instant invalidates an earlier opening mark using the ordinary action rules.

The report's `opening_holdings` separates contributed book basis from market
valuation and declares that source authenticity is not established. Cash and
lots are contributed at book amounts to the journal's `external_capital` account.
That account is an accounting balancing account, not an estimate of the
portfolio's opening market value or a cash-flow-adjusted performance measure.

## Persistent journal and browser

A journal `opening_lot` event has `id`, `timestamp`, `kind`, `instrument`,
`quantity`, `basis` and `acquired_at`. The timestamp is the import/opening instant;
the acquisition time is retained in the lot. Its postings debit inventory basis
and credit external capital in quote currency, with no cash posting.

Opening events must occur at the journal's first timestamp and before any event
other than deposits/opening lots. Supply them in nondecreasing acquisition order
per instrument. Equal dates preserve journal insertion order. Reusing an event ID
with the same payload returns its original receipt even after later activity;
changing the payload is rejected. A bad row rolls back the entire new batch.
Opening balances cannot be appended later to revise earlier FIFO calculations.

```sh
python3 -m alphacairn.portfolio --db ./opening-account.sqlite init opening-demo/portfolio-account.json
python3 -m alphacairn.portfolio --db ./opening-account.sqlite apply opening-demo/portfolio-opening-events.json
python3 -m alphacairn.portfolio --db ./opening-account.sqlite value opening-demo/portfolio-quotes.json
python3 -m alphacairn.portfolio --db ./opening-account.sqlite reconcile opening-demo/portfolio-statement.json
python3 -m alphacairn.portfolio --db ./opening-account.sqlite audit
```

The multi-asset example replaces two purchases with opening lots and reduces the
cash deposit by their basis. It preserves the independent final control: USD
7,200 cash, EUR 399 cash, six US shares with USD 360.60 basis, ten EU shares,
0.1 crypto units and USD 10,948.90 equity. Paste those events into the Portfolio
screen's Events editor and run the checks; the existing account, quotes and
statement match them. Export retains the normalized events and reproduction
inputs. No live broker connection is used.

## Strategies and research

A catalog-backed strategy accepts the same version-4 execution template without
bars/commands. Its first decision observes actual opening quantities and orders
only the difference from target inventory. The planning pass must reconcile with
a complete execution replay. Captured inputs and exported execution/strategy
bundles retain the lots, acquisition times and marks.

Research method identities retain the lot/basis configuration. Opening marks,
like FX observations and corporate actions, are time-varying realization inputs
and excluded from the method signature; the complete trial input identity still
covers them. Holdout access rules remain unchanged.

## Verification and remaining scope

Twenty-five opening-holdings checks cover acquisition order, cent allocation,
zero basis, foreign-currency crypto, stale/missing/future marks, concurrent
idempotence, atomic rejection, cached acquisition corruption, split/dividend
ownership, strategy sizing and portable replay. Installed CLI/API controls compare
fills with independent integer-cent arithmetic and replay without the source
scenario/journal. A retained 1,000-lot/50-instrument workload also matches independent
cash/basis/equity calculations and verifies its bundle.

Evidence: [installed controls](opening-holdings-verification.json),
[workload](opening-holdings-benchmark.json),
[browser path](opening-holdings-browser-verification.json).
Broker tax-lot imports, mid-run position transfers, shorts, derivatives, cash in
lieu, settlement accounting and broader provider integration remain open. Full
product and 20,000 useful-SLOC acceptance remain open.
