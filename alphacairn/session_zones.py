"""Bounded, portable timezone rules with explicit gap/fold resolution."""

import base64
import datetime as dt
import hashlib
import importlib.resources
import io
from pathlib import Path
import re
import struct
import zoneinfo

MAX_ZONE_BYTES = 1024 * 1024


