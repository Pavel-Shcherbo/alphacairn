"""Independent revision timelines, information cutoffs and storage controls."""

import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import localcontext
from pathlib import Path

from alphacairn.market_model import (
    canonical,
    observation,
    snapshot_identity,
    verify_snapshot,
)
from alphacairn.market_store import MarketCatalog
from alphacairn.market_research import decision_windows, read_snapshot, write_snapshot


def bar(session="2020-01-02", close="10", published=None, instrument="STOCK-A"):
    return {
        "instrument": instrument,
        "session": session,
        "opened_at": session + "T09:00:00Z",
        "closed_at": session + "T16:00:00Z",
        "published_at": published or session + "T16:01:00Z",
        "status": "active",
        "open": "10",
        "high": "30",
        "low": "1",
        "close": close,
        "volume": "100",
    }


def member(
    instrument="STOCK-A",
    start="2020-01-01",
    until=None,
    published="2019-12-31T12:00:00Z",
):
    return {
        "instrument": instrument,
        "universe": "TEST",
        "valid_from": start,
        "valid_until": until,
        "published_at": published,
        "status": "active",
    }


