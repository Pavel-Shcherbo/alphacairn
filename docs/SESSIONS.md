# Retained trading sessions

Alphacairn can compile an explicit operator schedule into a portable calendar and use it to validate execution bars. Calendars describe supplied assumptions. They do not claim to be an official exchange holiday feed, authenticated historical notices or settlement instructions.

## Local workflow

```sh
python -m alphacairn.sessions build examples/session-schedule.json --output /tmp/calendar.json
python -m alphacairn.sessions verify /tmp/calendar.json
python -m alphacairn.sessions session /tmp/calendar.json demo 2020-01-01
python -m alphacairn.sessions next-open /tmp/calendar.json demo 2020-01-04T12:00:00Z
python -m alphacairn.sessions advance /tmp/calendar.json demo 2020-01-03 1
python -m alphacairn.execution run examples/session-execution.json --output /tmp/session-study
```

Output paths are created exclusively. An existing calendar or study must not be overwritten. `sessions` emits JSON, exits 2 for invalid input/horizon/output errors and never downloads timezone or holiday data. `locate` returns `null` while the specified calendar is closed. Queries take a calendar ID; instrument bindings are explicit in the schedule.

## Schedule contract

Version 1 declares a source description, inclusive `starts_on`/`ends_on` date labels, calendars and an instrument-to-calendar map. Each calendar has an IANA timezone, unique weekday integers (Monday=0, Sunday=6), ordered local segments and explicit dated exceptions. An exception replaces the whole daily schedule. Empty segments close the date; nonempty segments may open a normally closed weekend. Every exception needs a reason.

Each segment has `open`/`close` endpoints containing local `time`, integer `day_offset` (-2 through 2 relative to the session label) and `fold` (null, 0 or 1). Midnight at the following day is `00:00` with offset 1. `24:00` and leap seconds are rejected. Overnight sessions, split sessions and shortened days are explicit. UTC intervals and successive session envelopes must be ordered without overlap.

A clock that never occurred because of a timezone jump is rejected. A clock that occurred twice requires an explicit fold choice. Resolution checks both candidates by converting to UTC and back; it does not silently normalize a nonexistent local clock. Continuous UTC sessions represent 24-hour crypto controls without a weekday closure. A local midnight-to-midnight day need not last 24 elapsed hours.

## Reproduction and queries

The portable document includes the normalized definition, exact bounded TZif bytes used for every timezone, their hashes, UTC sessions and a document digest. Verification regenerates all sessions using the embedded timezone entities, without reading the current system timezone database. Rehashing a modified UTC schedule does not make it pass. Hashes identify bytes and assumptions; they do not authenticate their provider.

Generation uses local system timezone files or an already installed `tzdata` package. Missing timezone data fails with an actionable error; nothing is installed automatically. Zone keys are bounded relative paths. Embedded TZif headers/counts and entity sizes are checked before parsing. Support is limited to TZif versions 1–3.

`locate` uses half-open intervals: an opening belongs to a segment and its closing does not. `next-open` searches segment openings, including the current opening unless `--exclusive` is supplied. It does not return the current instant merely because a segment is open. `advance` counts open daily session labels, not segments: Friday plus one may be Monday. For a closed base label, `--roll following` or `preceding` rolls first, then applies the signed count. This can describe separately supplied bank-day schedules; no automatic T+1/T+2, netting or broker settlement is implemented.

The retained horizon is finite. Queries and execution coverage require neighboring labels when overnight offsets could contribute intervals; they fail rather than extrapolate. Limits: 16 calendars, 3,661 labeled days, 25,000 calendar/day rows, 50,000 segments, eight segments per daily rule, 1,000 exceptions per calendar, 1,000 instrument bindings and an 8 MiB canonical calendar. Timezone entities are at most 1 MiB each, with a bounded inventory.

## Execution and strategies

Execution version 1 retains its existing explicit-bar behavior. Version 2 additionally requires `calendar` (the complete portable document) and `calendar_policy: {"require_all_sessions": true|false}`. Every account instrument must bind exactly once. Each supplied bar must match the first opening and last closing of its declared open session. A scenario or active-instrument interval cutting a session is rejected.

Strict coverage rejects a missing expected instrument/session bar. Permissive coverage retains the count and up to 100 missing labels in `calendar_validation`, with `complete: false`. Missing prices are never synthesized. Coverage checks are limited to 200,000 instrument/session pairs. Entirely inactive instruments contribute no expected sessions.

Orders may be submitted while a calendar is closed. Eligibility, cancellation and fills still use existing bar opens/closes and the engine's strict later-open rule. Split-session calendars validate the full daily bar envelope; they do not add a midday fill phase or infer an intraday price path. One bar per instrument/session remains the model limit. Closing-phase limit touches remain the existing explicit OHLC assumption.

Catalog strategy definitions may use a version-2 execution template with these same fields. Captured studies include the calendar/timezone entities and replay offline. The calendar constrains realized execution bars. It does not establish when holiday notices were historically available or change the separate publication/recording clocks of strategy signals.

The synthetic `session-execution.json` combines weekday stock bars and UTC continuous crypto bars. It has five expected instrument/sessions and two fills, including a Saturday crypto fill. Independent arithmetic: initial USD 100, purchases USD 50 + USD 20, no fees, final cash USD 30, positions 5 at USD 11 and 2 at USD 11, final equity USD 107. The retained verification file records installed CLI and exported replay checks. Official exchange adapters, settlement cash flows, actions during execution, intraday fills and browser calendar controls remain open.
