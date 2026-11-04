# Cash settlement and available funds

Version-5 execution and strategy studies distinguish trade-date holdings, settled
cash, purchase reservations and unsettled sale proceeds. Every outgoing cash
obligation is fully backed by existing settled cash. There is no borrowing or
use of unsettled sale proceeds to finance another purchase.

This is an explicit research model. The operator supplies all due-date rules and
calendar data; no current or historical legal/exchange settlement convention is
inferred. The bundled dates and closures are synthetic controls.

## Execution control

```sh
python3 -m alphacairn.resources ./cash-demo
python3 -m alphacairn.execution run cash-demo/settlement-execution.json --output ./cash-study
python3 -m alphacairn.execution verify ./cash-study
```

The example opens with five A shares and no cash. Three A shares sell on Friday
January 3, 2020 at USD 10, less USD 0.50. Its T+2 rule requires both synthetic
calendars; one is closed on January 6, so the USD 29.50 sale receivable settles on
January 8 at 17:00 UTC. A simultaneous B purchase remains unfunded through the
January 8 open. It executes two shares on January 9 for USD 24 plus USD 0.50 and
reserves USD 24.50 until January 13 at 17:00 UTC.

The example ends with USD 5 cash, two A shares with USD 16 basis and two B shares
with USD 24.50 basis. Marked equity is USD 49.00. Ending the study on January 9
instead retains USD 29.50 settled cash, USD 24.50 reserved, USD 5 available and a
USD 24.50 payable; equity is still USD 49.00.

## Explicit due dates

Version 5 extends the version-4 opening-holdings/action/calendar contract with a
required `settlement` policy. Versions 1–4 reject the additional field and retain
their immediate-cash behavior. A policy has version 1, a retained calendar document
or null, and exactly one rule per account instrument:

```json
{
  "version": 1,
  "calendar": null,
  "rules": [{"instrument": "COIN", "mode": "immediate"}]
}
```

An immediate rule settles each fill at its exact trade time. A business-day rule
has these fields instead:

```json
{
  "instrument": "A",
  "mode": "business_days",
  "lag": 2,
  "calendars": ["usd", "joint"],
  "trade_date_basis": "local_fill_date"
}
```

The retained document uses the existing portable session-calendar format, with
empty instrument bindings. Rules supply their own bindings. Build such documents
through `python3 -m alphacairn.sessions build`; timezone TZif bytes and complete
materialized sessions are retained, so replay does not use the host's current
zone database.

A rule can require 1–4 distinct calendars. A business date must be open in all of
them. Its cash due time is the latest UTC close among their final segments. Business
windows must stay within their labeled local day; overnight trading windows are
not accepted as bank-settlement windows. Calendar closures, shortened days and
extra opening days are supplied explicitly with ordinary calendar exceptions.

For `local_fill_date`, the first calendar's retained timezone determines trade
date. For `session_label`, the operator's bar label determines it. A positive lag
of 1–10 counts joint business dates strictly after trade date. Lag 0 first tries
that date and rolls to the next joint cutoff when the fill occurs after the cutoff.
Equality with the cutoff settles immediately. A positive-lag session label implying
settlement before its actual fill is rejected, rather than silently rolled.

Preview the exact declared result:

```sh
python3 -m alphacairn.settlements due cash-demo/settlement-policy.json --account cash-demo/settlement-account.json --instrument A --at 2020-01-03T09:00:00Z --session 2020-01-03
```

Every possible bar open/close is checked at compilation. The retained horizon
must cover its complete due date, even when the study ends sooner or the relevant
order never fills. The model never extrapolates missing calendar days.

## State and event ordering

At a buy fill, the position/FIFO lot is acquired immediately. The journal credits
a per-trade payable and debits inventory basis; settled cash is unchanged, while
the payable reserves that cash. At a sell fill, FIFO ownership/basis is released
and realized income is booked. Net proceeds become a per-trade receivable instead
of settled cash. If the sale fee exceeds proceeds, its deficit is a backed payable.
A zero-net sale still has one auditable settlement transition.

At due time, cash replaces the receivable, or cash pays the payable. Payments,
withdrawals, immediate trades and FX exchanges cannot consume another trade's
reservation. At a shared execution instant, existing cash settlements precede
expiry, closes, actions, commands and opens. A newly created same-instant claim
settles immediately. Dividend pay events credit both settled and available cash.

Positions, dividend ownership and later sales use trade-date quantities, including
positions whose purchase cash has not yet settled. This model does not add a
securities-delivery restriction or cash-account trading regulation. Netting,
failed settlement, counterparty/default risk, margin, broker tax lots and automated
provider notices remain outside this increment.

`report.cash` and fill `cash_after` mean settled cash in version 5. Separate
`available_cash`, `available_cash_after` and `reserved_cash_after` fields make
spendable funds explicit. Fill CSVs add due date and cash-reservation fields only
for version 5. The settlement report retains every trade's rule, source calendar
identity, due instant and final pending/settled status. Equity-curve points expose
the settled/reserved/available balances and pending count.

## Persistent journal

A `trade_pending` event has ordinary trade fields plus `settles_at`. It changes
trade-date holdings and cash claims; its due time cannot precede the trade. A
`trade_settlement` event has `trade_id` and cannot precede the parent's due time.
Its amount/currency come from the accepted parent, not another caller-supplied
amount. An identical event retry returns its original receipt; another settlement
ID for an already paid trade is rejected. Payment may occur after an instrument's
active interval because an existing cash claim still needs discharge.

The operator can settle due cash explicitly against an existing journal:

```sh
python3 -m alphacairn.portfolio --db ./cash-account.sqlite init cash-demo/portfolio-account.json
python3 -m alphacairn.portfolio --db ./cash-account.sqlite apply cash-demo/portfolio-settlement-events.json
python3 -m alphacairn.settlements pending --db ./cash-account.sqlite
python3 -m alphacairn.portfolio --db ./cash-account.sqlite reconcile cash-demo/portfolio-settlement-statement.json
python3 -m alphacairn.settlements settle-due --db ./cash-account.sqlite --at 2026-01-05T17:00:00Z --request-key purchase-paid
python3 -m alphacairn.settlements receipt --db ./cash-account.sqlite purchase-paid
python3 -m alphacairn.settlements settle-due --db ./cash-account.sqlite --at 2026-01-06T17:00:00Z --request-key sale-paid
python3 -m alphacairn.portfolio --db ./cash-account.sqlite audit
```

The separate multi-asset-account example has USD 100 settled, USD 21 reserved,
USD 79 available and a USD 12 receivable. After both cash payments it has USD 91
and one share with USD 10.50 basis. At the USD 12 mark, equity is USD 103 before
and after settlement.


`settle-due` saves its selected events and input-bound response in the same SQLite
transaction. Exact request retries return the original result; changed clock/limit
under the same key is rejected. A batch defaults to 100 trades, can process 1–1000,
and reports remaining due count. No-op responses are retained too; use a new key
to evaluate newly observed activity. A killed process or failed receipt insert
rolls back cash, claim accounts and payment markers together. This foreground
command does not run a timer or infer that a broker actually paid.

The service scans at most 10,000 pending trades and retains at most 10,000 batch
responses/64 MiB of response text. The journal's existing per-batch/JSON bounds
remain. Retention/deletion and supervised service controls remain open. Invalid
input/storage returns exit 2; successful pending/preview/settlement operations
return 0. A journal reconcile discrepancy uses its existing exit 1.

## Reproduce the cash and equity checks

Use a fresh working directory with Alphacairn installed. Export the examples and
initialize a new journal; do not reuse a journal from another walkthrough:

```sh
python3 -m alphacairn.resources ./cash-demo
python3 -m alphacairn.portfolio --db ./equity-check.sqlite init cash-demo/portfolio-account.json
python3 -m alphacairn.portfolio --db ./equity-check.sqlite apply cash-demo/portfolio-settlement-events.json
```

For this control, use one explicitly supplied USD 12 mark at a timestamp after
both settlement cutoffs. The same snapshot is used on both states to isolate
settlement from market-price changes. This is a synthetic state comparison, not
an as-of trading decision or a claim about historical market prices. The bundled
`portfolio-settlement-quotes.json` has an earlier timestamp and is not the final
snapshot used here.

```sh
python3 - <<'PYTHON'
import json
from pathlib import Path
Path("cash-demo/equity-check-quotes.json").write_text(json.dumps({
    "as_of": "2026-01-06T18:00:00Z",
    "marks": {"equity:demo-us": {
        "price": "12", "timestamp": "2026-01-06T18:00:00Z"
    }},
    "fx": {}
}))
PYTHON
python3 -m alphacairn.portfolio --db ./equity-check.sqlite state
python3 -m alphacairn.portfolio --db ./equity-check.sqlite value cash-demo/equity-check-quotes.json
python3 -m alphacairn.portfolio --db ./equity-check.sqlite reconcile cash-demo/portfolio-settlement-statement.json
python3 -m alphacairn.settlements settle-due --db ./equity-check.sqlite --at 2026-01-05T17:00:00Z --request-key purchase-paid
python3 -m alphacairn.settlements settle-due --db ./equity-check.sqlite --at 2026-01-06T17:00:00Z --request-key sale-paid
python3 -m alphacairn.portfolio --db ./equity-check.sqlite state
python3 -m alphacairn.portfolio --db ./equity-check.sqlite value cash-demo/equity-check-quotes.json
python3 -m alphacairn.portfolio --db ./equity-check.sqlite audit
```

Expected controls:

| Output | Before payments | After both payments |
| --- | --- | --- |
| `settlement.cash`, USD settled | 100.00 | 91.00 |
| USD reserved | 21.00 | 0.00 |
| USD available | 79.00 | 91.00 |
| Number of pending settlements | 2 | 0 |
| `value` equity | 103.00 | 103.00 |

The pre-payment statement returns `matched: true`; it describes pending claims
and is checked before they are discharged. The final journal audit returns
`passed: true`. Do not treat that pre-payment statement as a post-payment one.

Before payment, equity is 100 cash minus 21 payable plus 12 receivable plus the
remaining position marked at 12. Afterwards, it is 91 cash plus that same 12
position. The release of reservations changes available funds; it does not
create profit. Both the statement match and the audit are local controls on
synthetic inputs, not evidence of live broker payment or production acceptance.


## Valuation, statements and risk

Valuation includes positive receivables and negative payables separately from
positions and settled cash. Cash plus signed trade claims convert as one currency
pool with half-even rounding, preventing a one-cent change merely when a claim
becomes cash. Per-row claim conversions allocate the residual deterministically
in trade-ID order. Positions and dividend assets retain their separate conversion
rules. Missing/stale marks or FX remain incomplete rather than zero.

A statement with outstanding claims must explicitly supply a `settlements` object
keyed by trade ID, each containing `currency`, `kind`, `amount` and `settles_at`.
Missing settlement coverage fails reconciliation; it is not filled from the
journal. Cash/position missing keys retain their zero-balance convention. Amount,
direction, due-date, extra and omitted claim differences are visible.

The Portfolio screen exposes an Independent statement editor, settled/reserved/
available rows and pending claims. Editing any input clears prior result/export
and settlement rows; late responses cannot reinstate old results. Use the three
`portfolio-settlement-*.json` examples with the bundled account. Browser
calculations are disposable; the CLI retains a persistent journal.

Risk studies retain signed trade-cash exposures. Stress components reconcile to
equity and currency factors net cash claims before the active-factor limit. Static
risk revalues current claims; it does not simulate future default, liquidity or
settlement failure. Strategy planning processes the same cash clock as execution
and must reproduce its complete settlement report. Research method identities
retain recurring calendar/cutoff rules and TZif identities; dated horizons and
exceptions remain in the full captured trial inputs.

## Verified increment

33 new checks cover joint holidays, cutoffs, DST without host timezone lookup,
coverage rejection, reservations, fees exceeding proceeds, zero claims, FIFO,
corporate actions, strategy replay, signed risk/stress, FX rounding, statement
coverage, killed-process rollback and concurrent exact retries. Clean installed
CLI/API controls include complete execution, persistent payments, frozen risk
capture and portable replay after source database/scenario removal.

The retained workload has 100 instruments, 200 fills and 200 cash settlements.
Independent rational arithmetic gives USD 10,098 final cash. Three separate
persistent batches of 50/50/100 settlements produce the exact simulation journal
state. Browser downloads reproduce independently, with USD 103 equity before/after
and deliberate statement/early-payment/race failures checked.

Evidence: [installed controls](settlement-verification.json),
[workload](settlement-benchmark.json), [browser checks](settlement-browser-verification.json),
[pending download](settlement-browser-pending.json), [paid download](settlement-browser-paid.json).
Full product/20,000 useful-SLOC acceptance remains open.
