"""Revision-aware decision windows and portable market snapshot verification."""

import os
import tempfile
from decimal import Decimal
from pathlib import Path

from .market_model import (
    MAX_BYTES,
    canonical,
    day,
    decode,
    digest,
    identifier,
    instant,
    verify_snapshot,
)
from .money import arithmetic, decimal_value, text


def write_snapshot(snapshot, destination):
    verify_snapshot(snapshot)
    payload = canonical(snapshot) + b"\n"
    if len(payload) > MAX_BYTES:
        raise ValueError("portable snapshot exceeds 16 MiB; narrow the query")
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".market-", dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "path": str(destination),
        "sha256": snapshot["sha256"],
        "records": len(snapshot["records"]),
    }


