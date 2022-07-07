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


