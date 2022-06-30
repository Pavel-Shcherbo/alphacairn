"""Indexed session queries and explicit execution coverage diagnostics."""

from bisect import bisect_left, bisect_right
import copy
import datetime as dt

from .instruments import timestamp, timestamp_text
from .session_model import day, verify_calendar


class SessionCalendar:
    pass
