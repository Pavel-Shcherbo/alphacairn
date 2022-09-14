"""Build portable operator calendars and query retained session horizons."""

import argparse
import json
from pathlib import Path

from .execution_export import parse_data
from .session_calendar import SessionCalendar
from .session_model import MAX_BYTES, build_calendar


