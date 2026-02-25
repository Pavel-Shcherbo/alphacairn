# Multi-instrument order execution

This local simulator executes explicit orders against declared bars and known liquidity budgets. It shares instrument contracts, exact monetary arithmetic, the portfolio journal and valuation rules with the rest of Alphacairn. It has no exchange, broker, credential or network endpoint. Bundled observations are synthetic controls.

## Run and independently reproduce

```sh
python3 -m alphacairn.execution run examples/execution-scenario.json --output execution-results
python3 -m alphacairn.execution verify execution-results
```

The output directory must be new; existing files/directories are preserved. Without `--output`, `run` prints the complete report. For an installed wheel, export examples with `python3 -m alphacairn.resources demo` and use `demo/execution-scenario.json`.

The bundled example starts with USD 1,000 and EUR 200, buys two synthetic equities and a spot cryptoasset over limited-liquidity bars, then sells part of the US equity. Seven fills complete four orders. Expected final cash is USD 924.00 and EUR 137.80, quantities are 3 US equity, 3 EU equity and 0.8 crypto. Fees total USD 2.50 and EUR 0.20. Final marks are 11, 21 and 54 respectively, with EUR/USD valuation factor 1.2:

`924 + 3×11 + 0.8×54 + (137.8 + 3×21)×1.2 = 1241.16 USD`.

The remaining US-equity FIFO basis is 34.67; EU-equity basis 62.20; crypto basis 42.50. The independent installed-package check reconstructs cash and quantities from exported CSV using rational arithmetic, checks the final valuation and independently reruns the bundle. These controls verify accounting and declared model behavior, not historical market fills or investment performance.

## Scenario contract

The input has exactly `version`, `account`, `starts_at`, `ends_at`, `initial_cash`, `fees`, `slippage_bps`, `max_mark_age_seconds`, `bars`, `commands`, `fx`. Version is integer 1. Times require explicit UTC offsets and normalize to UTC microseconds. The start must precede the end; commands, bars and FX observations must lie inside that interval.

`account` uses the existing account/instrument specification: declared currencies and rounding places, stable instrument IDs, equity or crypto_spot kind, quote currency, quantity step, price tick and optional active interval. There are no initial securities positions: a scenario begins with explicitly funded nonnegative cash by currency. Omitted declared cash balances default to zero. All financial inputs use bounded exact decimal text or integers; JSON floating-point amounts and booleans are rejected by monetary contracts.

`fees` has `rate_bps` and `minimum`, a per-currency object. Omitted minima default to zero. Rates and `slippage_bps` must be nonnegative and below 10,000 basis points. `max_mark_age_seconds` is an integer from zero through 366 days. Existing 38-significant-digit/18-exponent input bounds and account currency precision apply. Supported-range arithmetic errors stop the calculation rather than producing a successful partial report.

## Bars and liquidity

Each bar has exactly `instrument`, `session`, `opened_at`, `closed_at`, `open`, `high`, `low`, `close`, `liquidity`, `liquidity_known_at`.

Prices are positive, tick-aligned, and low/high must enclose both open and close. Sessions use YYYY-MM-DD. This version accepts one bar per instrument/session, without overlapping intervals for one instrument. Opening/closing times are supplied explicitly; no exchange timezone, holiday or auction schedule is inferred. Bars must remain within the instrument's declared active interval.

Liquidity is a nonnegative quantity budget, rounded down to the instrument's quantity step. Its knowledge timestamp cannot follow the bar opening. It is shared by buys and sells, and by open and close phases, with no replenishment within the bar. It is a separately supplied execution assumption, not realized daily trading volume. The simulator does not claim that such a budget was available historically merely because an input file declares its timestamp.

## Orders and commands

Commands must have nondecreasing `at` timestamps and unique IDs. A submit command requires `action: "submit"`, `id`, `at`, `instrument`, `side`, `kind`, `quantity`, `time_in_force`; optional fields are `limit` and `expires_at`.

- `side`: buy or sell. Quantity is positive and step-aligned.
- `kind`: market or limit. Limit orders require a positive tick-aligned limit. Market orders cannot declare a non-null limit.
- `time_in_force`: GTC, IOC or DAY, with the model-specific meanings below.
- `expires_at`: if supplied, strictly later than submission. The instrument's active end also bounds the effective expiry.

A cancel command has exactly `action: "cancel"`, unique command `id`, `at`, `order_id`, and must reference an earlier submit command. A request against a terminal order is recorded as ignored. These are simulated order instructions, not a brokerage order API.

An order is eligible only at a bar opening strictly later than submission. Submission exactly at opening or inside a bar waits for the next eligible bar. A command supplied after the final bar can remain open at scenario end; the report exposes this instead of inventing a fill.

Cancellation requests become effective at the next opening of that order's instrument strictly after the request. A request during a bar does not retroactively remove a close-phase fill from that bar. This explicit coarse-bar rule is not a claim of continuous intraday cancellation handling.

## Fill phases and resource allocation

At each instant, explicit expiry is processed before close-phase fills. Closing bars are processed before new commands and opening bars; FX observations at that instant are available to the subsequent valuation. Across instruments sharing one execution phase, order submission time and original command sequence determine cash allocation. Alphabetical instrument names do not establish priority.

At open, market orders use the opening price with adverse percentage slippage and adverse tick rounding: up for a buy, down for a sell. Nonpositive resulting sell prices do not fill. A marketable limit can receive opening-price improvement; slippage is capped at its limit. Buy limits are marketable when open is no greater than the limit; sell limits when open is no less.

Other eligible limit orders can fill at their limit on bar close if the observed low/high touches it. This is a declared close-phase fill model. It does not assert when a touch occurred or infer a unique OHLC path. Expiry at or before the close prevents that unobserved intrabar fill. Same-phase allocation across orders remains deterministic, without claiming real venue queue priority.

Each fill is limited by remaining order quantity, remaining bar liquidity, quote-currency cash or available long position. Pending orders reserve neither money nor shares. A binary lot search finds the largest affordable buy, including rounded notional, percentage fee and per-fill minimum. A sell cannot exceed holdings or make quote-currency cash negative when a minimum fee exceeds proceeds. A notional that rounds to zero does not fill. There is no margin, shorting, automatic currency exchange or cross-currency cash substitution.

The fee is the greater of the half-even rounded percentage fee and currency minimum. Every partial fill incurs its own fee; the minimum is not deferred to order completion. Notional and fee settle immediately in quote currency. The simulator does not model unsettled funds or a settlement calendar.

Time-in-force meanings:

- IOC: only the first eligible open is attempted; any remainder cancels immediately. An unmarketable limit does not wait for the bar low/high.
- DAY: can use open and eligible limit-touch phases of its first eligible bar; any remainder cancels at that bar's close. “DAY” here names this bar lifecycle, not an inferred venue session.
- GTC: remaining quantity persists across later eligible bars until filled, cancelled, expired or the scenario ends. A partially filled market GTC attempts later opens.

Report statuses are open, partially_filled, filled, cancelled or expired. `completed: true` means the scenario calculation finished, not that all orders filled or that every valuation is complete. Inspect `open_order_count`, order reasons and valuation completeness. Zero cash, no fills, insufficient funds and untouched limits are valid modeled outcomes.

## Accounting and valuation

The order book maintains cash and position quantities independently. Its funding/fill events are then applied to a fresh portfolio journal. Final cash and quantities must match; the journal independently replays its full history, balanced postings and FIFO lots. Any mismatch raises an error. Final journal valuation must also agree with the simulator's last equity point.

Close marks become available only when their bars close. FX observations have exactly `currency`, `at`, `rate`; rate means base units per quote-currency unit. A base-currency quote must equal one. Quotes are selected once their supplied time is reached, without automatic FX conversion transactions. Cash and each position value convert separately with half-even rounding, matching the journal valuation.

Missing/stale marks or FX make `equity` null while retaining `known_base_value` and explicit missing-input diagnostics. Held foreign positions still require FX when their rounded quote value is zero. The curve retains compact missing diagnostics and quote-currency subtotals; `quote_values_partial` identifies subtotals missing position marks. Final valuation retains fuller diagnostics and warnings about holdings after an active interval. Positions are not forcibly liquidated at the end, and a delisting does not automatically become a sale or a zero mark.

## Portable evidence and verification

A new export directory contains normalized `scenario.json`, complete `report.json`, replayable `ledger-events.json`, and `fills.csv`, `orders.csv`, `equity.csv`. `manifest.json` is written last as the completion marker and lists exact file bytes/hashes plus scenario and report identities. No wall-clock creation timestamp, random identifier or temporary path enters the report. Repeating the same normalized scenario produces identical bundle bytes.

`verify DIRECTORY` checks allowed files, symlinks, byte/hash bounds, then re-executes the scenario and compares the entire report and every rendered output. Rehashing a changed CSV in the manifest cannot turn it into a successful replay. This verifies self-contained reproducibility, not provider authenticity: hashes are not signatures and the caller's declared commands/liquidity/times remain assumptions. Exported average fill price is a descriptive weighted average and need not lie on an executable tick.

Exports are create-only; existing directories and symlinks are preserved. A failed write removes only the newly created output directory. Readers reject missing completion manifests or unexpected entries. There is no promise of atomic directory visibility or cross-directory power-loss durability. CLI input/storage failures exit 2; successful run/verification exits 0. A valid run can retain open orders or incomplete equity; neither is silently reported as a filled portfolio.

## Bounds and remaining work

Input: 8 MiB, 10,000 bars, 2,000 commands, 1,000 submitted orders and 10,000 FX observations. At most two million instrument-relevant order/bar evaluations are accepted. Funding plus fills is capped to 10,000 journal events; the operational trace to 20,000 events. Equity-curve content is capped to 8 MiB, compact reports to 24 MiB, rendered files to 24 MiB each (normalized scenario 8 MiB), and combined bundle content to 48 MiB. Cancellation is checked between timeline instants and around journal replay; inner bounded accounting operations are not a real-time interrupt mechanism.

Strategy-to-order generation, direct point-in-time catalog adapters, corporate-action-adjusted execution, trading/settlement calendars, initial holdings, stop/conditional orders, venue queue models, derivatives/funding/margin, browser execution controls and hosted/multi-user operation remain open. Full product scope and 20,000 useful production SLOC remain open.

Version 4 adds explicit initial FIFO lots and opening marks, preserving the version-3 action/calendar contract. See [opening holdings](OPENING_HOLDINGS.md) for fields, sizing, basis and replay controls.

[Cash settlement](SETTLEMENT.md) extends the model with explicit due calendars, backed reservations, pending cash claims and independently replayed execution/journal/risk controls. Older execution contracts retain immediate-cash behavior.
