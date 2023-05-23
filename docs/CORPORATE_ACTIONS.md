# Declared corporate actions

Execution version 3 supports explicit equity splits and cash-dividend entitlement/payment clocks. It uses raw unadjusted bars, preserves original fills and independently reconciles settled cash, FIFO lots and outstanding dividend assets. It does not infer issuer actions or exchange entitlement rules from price jumps.

## Run the control

```sh
python -m alphacairn.execution run examples/corporate-execution.json --output /tmp/corporate-study
python -m alphacairn.execution verify /tmp/corporate-study
```

Export destinations are created exclusively. Version 1 keeps its original bar contract; version 2 keeps mandatory retained calendars. Version 3 adds `corporate_actions` and `price_basis: "unadjusted"`. It requires explicit `calendar`/`calendar_policy` fields: either both null or the same retained-calendar contract as version 2. Declaring adjusted prices is rejected to avoid silently double-applying a split.

The synthetic control starts with USD 1,000. A ten-share buy fills four shares at 10 before a 2:1 split. The position becomes eight shares; the remaining buy becomes twelve current-unit shares. Two subsequent six-share fills cost 30 and 36. A later sell fills four of its seven shares at 6 because the older buy consumes the rest of the shared liquidity. Final cash is 918, position 16, FIFO basis 86 and unrealized marked value 96.

At the split instant the example also declares a 0.50/share dividend on eight eligible shares: gross 4, withholding 1 and net receivable 3. Payment is beyond the study end. Final equity is 918 + 96 + 3 = 1,017. Extending the study through payment moves 3 from receivables into settled cash, preserving that equity. These are synthetic arithmetic controls, not market-return claims.

## Input clocks

Each action needs a unique stable ID, an equity instrument and `known_at` no later than its effective/ex instant. Up to 200 actions and one million action/bar coverage checks are supported. No split or dividend ex instant may fall strictly inside a supplied full-session bar. Whole actions are rejected if the supplied timestamps or terms cannot be represented by this model.

A split declares `at`, positive integer `numerator`/`denominator` (each at most one million, unequal) and `order_policy` (`cancel` or `adjust`). Two splits for one instrument cannot share an effective instant. A split before execution start may serve as a historical signal normalization reference; it is not applied to nonexistent initial holdings or represented as an executed action. Effective actions cannot follow execution end.

A cash dividend declares `ex_at`, `pay_at`, positive `amount_per_share` and `withholding_bps` from zero through 10,000. Execution start must not follow ex time; payment must not precede it. Payment may follow study end or the instrument's active interval. In that case an earned asset remains outstanding. No initial-position entitlement is invented.

At a shared instant the execution phase order is explicit: expiry; old-bar close fills/marks; splits; dividend entitlement; dividend payment; commands/strategy decisions; new-bar opens. For example, a buyer at the same opening as an ex instant is excluded, while a close fill at the same instant precedes this model's entitlement capture. These are caller-chosen simulation clocks, not an assertion of any exchange's entitlement convention.

## Splits and working orders

Positions and every open FIFO lot must convert exactly to the declared quantity step. Fractional remainders or nonterminating unsupported quantities fail; there is no invented cash-in-lieu price. FIFO basis is preserved.

`cancel` cancels existing live orders at effectiveness. `adjust` converts live remaining/filled quantities to current units, divides limit prices by the split ratio and requires exact quantity-step/tick alignment. It does not guess an exchange rounding direction. Pending cancellation intent and submission priority remain intact. Already terminal orders and future scheduled submissions retain their declared units. A command submitted at the action instant is a new-unit command.

Version-3 order reports keep `original_definition` and a full `corporate_adjustments` trail. Working quantity, filled quantity and average fill price can be expressed in newer units. Original fill rows remain immutable historical-unit observations, so summing their raw quantities across a split is not a valid current-unit total. Fee and nominal price-quantity sums are not multiplied into artificial money.

A split clears the old-unit mark. A dividend ex event also clears the earlier cum-dividend mark to avoid combining that old price with a newly earned asset. Equity is incomplete until an appropriate new-unit closing mark is available; the engine never multiplies new shares by an obsolete old-share price. Existing open/close fill and OHLC-touch assumptions still apply. Intraday paths, symbol transformations, mergers and delistings with cash consideration are not inferred.

## Dividend assets and cash

Entitlement captures actual holdings at ex time, after any same-instant split. Gross rounds half-even in quote currency. Withholding rounds half-even from that gross, and net becomes a receivable. It enters equity but is excluded from spendable settled cash. Later sales or splits do not erase or multiply this previously earned monetary claim.

Payment transfers the claim to cash once, without recognizing income twice. No-position or rounded-zero gross entitlements create no journal credit. Full withholding creates a zero-net entitlement with a payment marker that still prevents duplicate settlement. The model does not discount receivables or estimate credit risk, broker fees or actual tax rates.

The general portfolio journal now accepts `dividend_accrual` (instrument, gross, withholding) and `dividend_payment` (accrual_id). Existing `dividend` keeps immediate cash-payment semantics. Accrual posts net to `dividend_receivable:EVENT_ID`, withholding to expense and gross to dividend income. Payment clears that asset and credits cash; a zero-valued settlement marker prevents a second payment under another event ID. Existing event-ID retries remain idempotent.

The extension uses existing append-only events/postings and an additive lookup index. Existing ledgers retain their schema version and original cash/trade behavior. Journal replay reconstructs the new postings. Direct journal accruals represent caller-declared amounts; execution additionally rechecks eligible ownership from independently reconstructed FIFO lots and recomputes gross/withholding with rational integer-unit rounding.

Valuation converts each outstanding claim separately using the same explicit as-of FX policy as cash/positions. Missing FX makes equity incomplete, even if the underlying shares were sold. Fully paid claims do not add value. Original version-1/2 results without dividend asset accounts keep their existing valuation shape.

## Captured strategies

A catalog strategy may use the version-3 execution template. Planning applies the same split/entitlement/payment phases before a same-instant decision, then the ordinary execution replay must reproduce orders, fills, cash, action reports and outstanding claims.

Signals use captured unadjusted closes normalized into decision-time share units with declared splits that are effective and known by that decision. Original observations and hashes are retained. Ratio products and the above-mean predicate use exact rational arithmetic; decimal means are display values. Future split factors cannot alter an earlier decision. Normalization is capped at two million action/observation checks and bounded rational precision.

`split_actions` and the signal-price basis are recorded per feature. Cash dividends do not adjust the signal price history into a total-return series. Target quantities remain literal units at each decision; a split does not automatically enlarge the researcher's declared fixed target. No action feed authenticity or historical notice completeness is established by including a supplied action list.

## Current limits

Initial holdings, cash-in-lieu policies, rights/spinoffs/mergers, payment corrections, issuer-action ingestion, price-basis provenance, total-return signal policies, broker settlement, corporate-action browser controls and the broad product/20,000 useful-SLOC requirement remain open. Synthetic and portable replay verification is recorded separately from full portfolio acceptance.

## Verified checkpoint

Twenty-six new corporate-action checks and 189 Alphacairn tests passed. Clean installed execution/export, create-only destination preservation, independent Fraction cash/FIFO/receivable controls, paid/unpaid cases, ex-mark invalidation and captured strategy replay without its source catalog passed. Evidence: `corporate-action-verification.json`.

A retained neutral-price workload used 100 instruments, 300 bars, 200 actions, 100 fills and 401 journal events. One hundred dividend entitlements were checked against FIFO journal ownership. Final quantities were 400 shares, settled cash 98,180 and equity 100,180, including 180 net dividends. The exported bundle replayed successfully. Timings, memory, retained bundle path and code identities are in `corporate-action-benchmark.json`; the reproducible workload script is in local planning tools. This is a synthetic qualification workload, not a performance or return guarantee.
