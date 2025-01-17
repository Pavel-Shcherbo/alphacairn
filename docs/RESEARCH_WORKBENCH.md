# Saved experiments workbench

Start `python3 -m alphacairn.web` and open
`http://127.0.0.1:8412/research.html`, or choose **Saved experiments** in the existing
workbench. The page uses the same frozen risk/strategy registry as the CLI.
It retains failed and incomplete attempts alongside successful ones.

## Run a study

1. Open a project. Project identifiers scope studies and request receipts; they
   are local namespaces, not authenticated user accounts.
2. Expand **New study**, enter its hypothesis, family and explicit UTC windows,
   and create it. Development must end strictly before holdout begins. A saved
   declaration is immutable; changing its meaning requires another study name.
3. Expand **Register frozen inputs**. Import a risk or strategy input JSON exported
   by the CLI, or load one of the clearly labelled synthetic risk controls.
   The document must retain its valid content hash and fit the study window.
4. Register an attempt, then run it from the comparison table. The table preserves
   registration order, including invalid-quote failures and incomplete history.
   Inspection shows the saved result and input identity. Risk results include
   exact base values, data coverage and the declared price/FX stress outcomes.
5. Resolve every registered development attempt before locking a successful
   development selection. Locking closes further development registration.
6. Register holdout inputs with the locked method and the declared holdout window.
   Enter an operator/reason and acknowledge access before running, inspecting,
   comparing or exporting holdout data. Each distinct accepted operation is
   recorded. Ordinary refreshes display metadata while withholding holdout figures.

The later-window synthetic control shifts the declared sample clocks by 31 days.
It demonstrates partition handling; it does not provide later real market data.
Risk control examples are not substitutes for a provider history or a trading
recommendation. A strategy attempt can import the same captured input document
used by `alphacairn.strategy`; its saved execution result is available in the
inspector and portable evidence export.

## Recovery and consistency

Foreground browser operations use one ingestion-independent SQLite transaction
covering their registry changes and saved response. Two simultaneous requests
with the same project/key/content return the same response, including selection,
execution, inspection and export. Reusing the key for changed content is rejected.
Response content hashes detect changed cached response bytes.

The browser retains the exact pending request in tab-scoped `sessionStorage`
before sending it. This includes frozen input data for registration, but no saved
result. Reloading the tab offers **Recover saved response**. It first reads the
existing response; if none is found, it resubmits the identical retained request
with the same key. A delayed original request and the retry therefore converge
on one operation. A holdout recovery still requires the checkbox. If tab storage
is unavailable or full, the original submission stops before being sent.

Keep that browser tab private on a shared machine. Closing the tab can discard
its pending request, while accepted studies/trials remain in the server database.
The page does not claim that absence of a response alone proves an operation
failed. Operator and reason strings identify local declarations, not verified
identities.

Computation runs in the foreground under the local write transaction. Terminating
the process rolls back its start, result and response together, leaving an already
registered attempt ready to run. This differs from the separate-phase CLI runner:
an expired CLI execution remains visible as running until explicitly recovered
at its recorded generation. Recovery retains an interrupted attempt without
inventing a completed result. A browser foreground crash does not create a
durable execution-start event that its transaction never committed.

Study metadata, development comparisons, audit and each event page come from one
database snapshot. A late view response cannot replace the current project/study.
Holdout event payloads in ordinary views are redacted; the full hash-chain evidence
is available through an explicit, audited export. Export replays the chosen trial
and includes the complete registered-attempt/access context at export time.
Subsequent study events do not rewrite an existing downloaded file.

## HTTP interface

All desk operations use `POST /api/research`, JSON and `X-Local-Request: 1`.
The host must be the printed loopback host; a foreign Origin is rejected.
Duplicate fields, nonfinite JSON numbers and unsupported request fields fail.

| Action | Required fields beyond `action` |
|---|---|
| `examples` | None; returns synthetic declaration and controls |
| `list` | `project` |
| `view` | `project`, `study`; optional `after`, `limit` for event paging |
| `receipt` | `project`, `request_key` |
| `create` | `project`, `request_key`, `definition` |
| `register` | `project`, `request_key`, `study`, `inputs`, `partition`, `label` |
| `run`, `inspect`, `export` | `project`, `request_key`, `study`, `trial`, `actor`, `reason`; `acknowledge_holdout: true` for holdout |
| `select` | `project`, `request_key`, `study`, `trial`, `actor`, `reason` |
| `compare` | `project`, `request_key`, `study`, `actor`, `reason`, `include_holdout`; acknowledgement when true |
| `recover` | `project`, `request_key`, `study`, `trial`, `actor`, `reason`, `generation` |

The selected-study binding is checked before a trial operation. `view` never
returns a holdout result. `receipt` returns a prior response for that exact
project/key without logging another access; it is response recovery, not a new
independent inspection. This local host has no authentication or remote-sharing
service and must not be exposed as one.

## Limits and evidence

State lives in `.local/alphacairn/research.sqlite`, relative to the working
directory, or under `ALPHACAIRN_STATE_DIR`. Installed package directories stay
unchanged. Limits: 8 MiB request, 4 MiB browser trial input, 16 MiB response,
10,000 retained desk receipts, 200 studies, 100 trials per study, 20,000 events
per complete audit and the registry's 256 MiB SQLite page budget. Event pages
contain 1–100 entries; comparison contains every registered attempt. Large inputs
or exports can use the CLI's documented wider bounds. Simultaneous local writers
can wait or time out; no hosted throughput or multi-user claim is made.

Desktop and 390-pixel browser controls covered failed/incomplete attempts,
selection, acknowledgement, delayed responses, network loss before and after
server commit, reload recovery and a downloaded replay. The table scrolls within
its own region on narrow screens. Monetary text retains decimal strings; only
bar widths use approximate display arithmetic. The calculation and exported
money remain in the exact accounting engine.

Evidence: `research-workbench-verification.json` records the installed HTTP/CLI
controls and independent SQLite/money reconciliation;
`research-browser-verification.json` records browser interactions and hashes of
the inspected screenshots/download. These checks do not establish external data
blindness, source authenticity, predictive validity or full product acceptance.

A retained synthetic browser download is included as `docs/research-study-evidence.json`. Replay it independently with `python3 -m alphacairn.studies verify docs/research-study-evidence.json`; this command does not need the original registry.
