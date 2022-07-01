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

