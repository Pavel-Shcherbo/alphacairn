"""Indexed session queries and explicit execution coverage diagnostics."""

from bisect import bisect_left, bisect_right
import copy
import datetime as dt

from .instruments import timestamp, timestamp_text
from .session_model import day, verify_calendar


class SessionCalendar:
    def __init__(self, document):
        self.document, self.zones = verify_calendar(document)
        self.definition = self.document["definition"]
        self.calendars = {row["id"]: row for row in self.definition["calendars"]}
        self.rows = {name: [] for name in self.calendars}
        self.labels = {}
        self.segments = {name: [] for name in self.calendars}
        for row in self.document["sessions"]:
            self.labels[row["calendar"], row["session"]] = row
            if row["segments"]:
                self.rows[row["calendar"]].append(row)
                self.segments[row["calendar"]].extend(
                    (
                        timestamp(window["opens_at"]),
                        timestamp(window["closes_at"]),
                        row["session"],
                    )
                    for window in row["segments"]
                )
        self.opens = {
            name: [timestamp(row["segments"][0]["opens_at"]) for row in rows]
            for name, rows in self.rows.items()
        }
        self.closes = {
            name: [timestamp(row["segments"][-1]["closes_at"]) for row in rows]
            for name, rows in self.rows.items()
        }
        self.segment_opens = {
            name: [row[0] for row in rows] for name, rows in self.segments.items()
        }
        self.open_labels = {
            name: [row["session"] for row in rows] for name, rows in self.rows.items()
        }

    def _name(self, name):
        if not isinstance(name, str) or name not in self.calendars:
            raise ValueError("unknown calendar ID")
        return name

    def session(self, name, label):
        self._name(name)
        day(label)
        try:
            return copy.deepcopy(self.labels[name, label])
        except KeyError as error:
            raise ValueError("session is outside retained horizon") from error

    def _covered_instant(self, name, when):
        zone = self.zones[self.calendars[self._name(name)]["timezone"]]
        local = when.astimezone(zone).date()
        # Require all labels that could contribute a segment at this instant.
        calendar = self.calendars[name]
        windows = list(calendar["segments"])
        for exception in calendar["exceptions"]:
            windows.extend(exception["segments"])
        lower = local - dt.timedelta(
            days=max([0] + [row["close"]["day_offset"] for row in windows])
        )
        upper = local - dt.timedelta(
            days=min([0] + [row["open"]["day_offset"] for row in windows])
        )
        if lower < day(self.definition["starts_on"]) or upper > day(
            self.definition["ends_on"]
        ):
            raise ValueError("retained horizon needs neighboring session labels")

    def locate(self, name, at):
        when = timestamp(at)
        self._covered_instant(name, when)
        index = bisect_right(self.segment_opens[name], when) - 1
        if index >= 0:
            opened, closed, label = self.segments[name][index]
            if opened <= when < closed:
                return {
                    "calendar": name,
                    "session": label,
                    "opens_at": timestamp_text(opened),
                    "closes_at": timestamp_text(closed),
                }
        return None

    def next_open(self, name, at, *, inclusive=True):
        if type(inclusive) is not bool:
            raise ValueError("inclusive must be boolean")
        when = timestamp(at)
        self._covered_instant(name, when)
        index = (bisect_left if inclusive else bisect_right)(
            self.segment_opens[name], when
        )
        if index == len(self.segments[name]):
            raise ValueError("no next opening within retained horizon")
        opened, closed, label = self.segments[name][index]
        return {
            "calendar": name,
            "session": label,
            "opens_at": timestamp_text(opened),
            "closes_at": timestamp_text(closed),
        }

    def advance(self, name, label, count, *, roll="raise"):
        row = self.session(name, label)
        if type(count) is not int or not -25000 <= count <= 25000:
            raise ValueError("session offset must be an integer within ±25,000")
        if roll not in ("raise", "following", "preceding"):
            raise ValueError("roll must be raise, following or preceding")
        labels = self.open_labels[name]
        index = bisect_left(labels, label)
        if not row["segments"]:
            if roll == "raise":
                raise ValueError("base label is a closed session")
            if roll == "preceding":
                index -= 1
            if not 0 <= index < len(labels):
                raise ValueError("rolled session is outside retained horizon")
        target = index + count
        if not 0 <= target < len(labels):
            raise ValueError("session offset extends beyond retained horizon")
        return self.session(name, labels[target])

    def overlapping(self, name, start, end):
        self._name(name)
        if start >= end:
            return []
        self._covered_instant(name, start)
        self._covered_instant(name, end - dt.timedelta(microseconds=1))
        left = bisect_right(self.closes[name], start)
        right = bisect_left(self.opens[name], end)
        return self.rows[name][left:right]


def validate_execution_calendar(scenario, account):
    index = SessionCalendar(scenario["calendar"])
    policy = scenario["calendar_policy"]
    if (
        not isinstance(policy, dict)
        or set(policy) != {"require_all_sessions"}
        or type(policy["require_all_sessions"]) is not bool
    ):
        raise ValueError("calendar policy requires boolean require_all_sessions")
    bindings = index.definition["instruments"]
    if set(bindings) != {item.id for item in account.instruments}:
        raise ValueError("calendar must bind every account instrument exactly once")
    supplied = {(bar["instrument"], bar["session"]): bar for bar in scenario["bars"]}
    for bar in supplied.values():
        row = index.session(bindings[bar["instrument"]], bar["session"])
        windows = row["segments"]
        if (
            not windows
            or timestamp(bar["opened_at"]) != timestamp(windows[0]["opens_at"])
            or timestamp(bar["closed_at"]) != timestamp(windows[-1]["closes_at"])
        ):
            raise ValueError("bar must match the full declared open-session envelope")
    expected, missing, samples = 0, 0, []
    for instrument in account.instruments:
        start = timestamp(scenario["starts_at"])
        end = timestamp(scenario["ends_at"])
        if instrument.active_from is not None:
            start = max(start, instrument.active_from)
        if instrument.active_until is not None:
            end = min(end, instrument.active_until)
        for row in index.overlapping(bindings[instrument.id], start, end):
            expected += 1
            if expected > 200000:
                raise ValueError(
                    "calendar coverage exceeds 200,000 instrument/session checks"
                )
            windows = row["segments"]
            if (
                timestamp(windows[0]["opens_at"]) < start
                or timestamp(windows[-1]["closes_at"]) > end
            ):
                raise ValueError("execution/active interval cuts a declared session")
            if (instrument.id, row["session"]) not in supplied:
                missing += 1
                if len(samples) < 100:
                    samples.append(
                        {"instrument": instrument.id, "session": row["session"]}
                    )
    if missing and policy["require_all_sessions"]:
        raise ValueError(f"missing bars for {missing} declared instrument/sessions")
    return {
        "calendar_sha256": index.document["sha256"],
        "expected_sessions": expected,
        "provided_bars": len(supplied),
        "missing_sessions": missing,
        "missing_sample": samples,
        "sample_truncated": missing > len(samples),
        "complete": missing == 0,
        "source_authenticated": False,
        "fill_phases": "existing full-session bar opens/closes only; no synthetic prices",
    }
