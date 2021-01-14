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


def read_snapshot(path):
    with Path(path).open("rb") as stream:
        snapshot = decode(stream.read(MAX_BYTES + 1))
    verify_snapshot(snapshot)
    return snapshot


def decision_windows(catalog, *, source, universe, decisions, start, lookback, clock):
    """Build features from each decision's own eligible revisions and universe."""
    source = identifier(source, "source")
    universe = identifier(universe, "universe")
    start = day(start, "start")
    if clock not in {"recorded", "published"}:
        raise ValueError("clock must explicitly select recorded or published")
    if type(lookback) is not int or not 1 <= lookback <= 1000:
        raise ValueError("lookback must be between 1 and 1000")
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= 100:
        raise ValueError("between 1 and 100 explicit decisions are required")
    normalized = []
    previous = None
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {"at", "session"}:
            raise ValueError("each decision requires at and session")
        at = instant(decision["at"], "decision time")
        session = day(decision["session"])
        if previous is not None and at <= previous or session < start:
            raise ValueError(
                "decision times must increase and sessions must not precede start"
            )
        previous = at
        normalized.append({"at": at, "session": session})
    with catalog.read_view() as view:
        output = []
        record_budget = 0
        for decision in normalized:
            universe_snapshot = view.snapshot(
                {
                    "kind": "membership",
                    "source": source,
                    "universe": universe,
                    "on": decision["session"],
                    "known_at": decision["at"],
                    "clock": clock,
                }
            )
            members = universe_snapshot["records"]
            if len(members) > 100:
                raise ValueError("decision window exceeds 100 instruments")
            features = []
            for member in members:
                instrument = member["observation"]["instrument"]
                snapshot = view.snapshot(
                    {
                        "kind": "bar",
                        "source": source,
                        "instrument": instrument,
                        "start": start,
                        "end": decision["session"],
                        "known_at": decision["at"],
                        "clock": clock,
                    }
                )
                records = snapshot["records"][-lookback:]
                record_budget += len(snapshot["records"])
                if record_budget > 100_000:
                    raise ValueError(
                        "decision window exceeds the 100,000 observation work budget"
                    )
                item = {
                    "instrument": instrument,
                    "snapshot_sha256": snapshot["sha256"],
                    "observations": [
                        record["observation_sha256"] for record in records
                    ],
                    "sessions": [
                        record["observation"]["session"] for record in records
                    ],
                    "available": len(records),
                    "ready": len(records) == lookback,
                    "last_close": None,
                    "mean_close": None,
                    "above_mean": None,
                }
                if records:
                    with arithmetic():
                        prices = [
                            decimal_value(record["observation"]["close"], positive=True)
                            for record in records
                        ]
                        item["last_close"] = text(prices[-1])
                        if item["ready"]:
                            mean = sum(prices, Decimal(0)) / Decimal(lookback)
                            item["mean_close"] = text(mean)
                            item["above_mean"] = prices[-1] > mean
                features.append(item)
            output.append(
                {
                    "decision": decision,
                    "universe_sha256": universe_snapshot["sha256"],
                    "features": features,
                }
            )
    result = {
        "schema": 1,
        "source": source,
        "universe": universe,
        "clock": clock,
        "start": start,
        "lookback": lookback,
        "windows": output,
        "assumptions": "Daily raw prices; publication clock is source-declared; recorded clock additionally gates local ingestion. Features are not fills, forecasts or investment recommendations. No automatic corporate-action adjustment or session calendar inference.",
    }
    result["sha256"] = digest(result)
    return result


def snapshot_bars(snapshot):
    """Convert one verified daily vintage to the existing float analytics input."""
    import csv
    import io
    from .backtest import parse_bars

    verify_snapshot(snapshot)
    if snapshot["query"]["kind"] != "bar":
        raise ValueError("research requires a bar snapshot")
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["date", "open", "close"])
    for record in snapshot["records"]:
        row = record["observation"]
        writer.writerow([row["session"], row["open"], row["close"]])
    stream.seek(0)
    return parse_bars(stream)
