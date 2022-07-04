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

