"""Caller-declared settlement dates over portable joint business-day calendars."""

from bisect import bisect_left, bisect_right
import copy

from .instruments import AccountSpec, timestamp, timestamp_text
from .session_calendar import SessionCalendar
from .session_model import day, fields


class SettlementClock:
    pass
