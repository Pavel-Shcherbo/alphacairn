"""Normalize operator schedules; materialize and replay bounded UTC sessions."""

import copy
import datetime as dt
import re

from .instruments import identity, timestamp_text
from .market_model import canonical, digest
from .session_zones import decode_zone, load_zone, zone_key

FORMAT = "alphacairn.session-calendar.v1"
MAX_BYTES = 8 * 1024 * 1024


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError(f"{label} fields do not match contract")


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("session label requires YYYY-MM-DD")
    result = dt.date.fromisoformat(value)
    if not 1900 <= result.year <= 2200:
        raise ValueError("calendar dates must be within 1900–2200")
    return result


def bounded_json(value):
    try:
        if len(canonical(value)) > MAX_BYTES:
            raise ValueError("calendar exceeds 8 MiB")
    except (TypeError, RecursionError) as error:
        raise ValueError("calendar requires bounded finite JSON") from error


def segments(value):
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("schedule requires 0–8 segments")
    result = []
    for item in value:
        fields(item, "open close", "segment")
        normalized = {}
        for key in ("open", "close"):
            endpoint = item[key]
            fields(endpoint, "time day_offset fold", "local endpoint")
            clock = endpoint["time"]
            if not isinstance(clock, str) or not re.fullmatch(
                r"\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?", clock
            ):
                raise ValueError("local clock requires HH:MM[:SS[.ffffff]]")
            if (
                int(clock[:2]) > 23
                or int(clock[3:5]) > 59
                or (len(clock) >= 8 and int(clock[6:8]) > 59)
            ):
                raise ValueError("local clock must be 00:00:00 through 23:59:59.999999")
            parsed = dt.time.fromisoformat(clock)
            offset, fold = endpoint["day_offset"], endpoint["fold"]
            if type(offset) is not int or not -2 <= offset <= 2:
                raise ValueError("day offset must be -2 through 2")
            if fold is not None and (type(fold) is not int or fold not in (0, 1)):
                raise ValueError("fold must be null, 0 or 1")
            normalized[key] = {
                "time": parsed.isoformat(timespec="microseconds"),
                "day_offset": offset,
                "fold": fold,
            }
        result.append(normalized)
    return result


def compile_schedule(definition):
    bounded_json(definition)
    fields(
        definition, "version source starts_on ends_on calendars instruments", "schedule"
    )
    if type(definition["version"]) is not int or definition["version"] != 1:
        raise ValueError("schedule requires version 1")
    source = definition["source"]
    if (
        not isinstance(source, str)
        or not source.strip()
        or len(source) > 256
        or any(ord(c) < 32 for c in source)
    ):
        raise ValueError("schedule requires a bounded source description")
    start, end = day(definition["starts_on"]), day(definition["ends_on"])
    if not 0 <= (end - start).days <= 3660:
        raise ValueError("schedule horizon must span 1–3661 days")
    calendars = definition["calendars"]
    if not isinstance(calendars, list) or not 1 <= len(calendars) <= 16:
        raise ValueError("schedule requires 1–16 calendars")
    if len(calendars) * ((end - start).days + 1) > 25000:
        raise ValueError("schedule exceeds 25,000 calendar/day records")
    result, names = [], set()
    for item in calendars:
        fields(item, "id timezone weekdays segments exceptions", "calendar")
        name = identity(item["id"], "calendar ID")
        if name in names:
            raise ValueError("duplicate calendar ID")
        names.add(name)
        weekdays = item["weekdays"]
        if (
            not isinstance(weekdays, list)
            or len(weekdays) > 7
            or any(type(n) is not int or not 0 <= n <= 6 for n in weekdays)
            or len(set(weekdays)) != len(weekdays)
        ):
            raise ValueError("weekdays require unique integers 0–6")
        exceptions = item["exceptions"]
        if not isinstance(exceptions, list) or len(exceptions) > 1000:
            raise ValueError("calendar supports at most 1000 explicit exceptions")
        normalized, labels = [], set()
        for exception in exceptions:
            fields(exception, "session segments reason", "calendar exception")
            label = day(exception["session"])
            reason = exception["reason"]
            if label in labels or not start <= label <= end:
                raise ValueError("exception labels must be unique and inside horizon")
            if (
                not isinstance(reason, str)
                or not reason.strip()
                or len(reason) > 256
                or any(ord(c) < 32 for c in reason)
            ):
                raise ValueError("exception requires a bounded reason")
            labels.add(label)
            normalized.append(
                {
                    "session": label.isoformat(),
                    "segments": segments(exception["segments"]),
                    "reason": reason,
                }
            )
        result.append(
            {
                "id": name,
                "timezone": zone_key(item["timezone"]),
                "weekdays": sorted(weekdays),
                "segments": segments(item["segments"]),
                "exceptions": sorted(normalized, key=lambda row: row["session"]),
            }
        )
    bindings = definition["instruments"]
    if not isinstance(bindings, dict) or len(bindings) > 1000:
        raise ValueError("schedule supports at most 1000 instrument bindings")
    for name, calendar in bindings.items():
        identity(name, "instrument ID")
        if not isinstance(calendar, str) or calendar not in names:
            raise ValueError("binding requires a declared calendar")
    return {
        "version": 1,
        "source": source,
        "starts_on": start.isoformat(),
        "ends_on": end.isoformat(),
        "calendars": sorted(result, key=lambda row: row["id"]),
        "instruments": dict(sorted(bindings.items())),
    }


def materialize(definition, zones):
    from .session_zones import resolve_local

    records, count = [], 0
    for calendar in definition["calendars"]:
        zone = zones[calendar["timezone"]]
        exceptions = {row["session"]: row for row in calendar["exceptions"]}
        previous = None
        label = day(definition["starts_on"])
        end = day(definition["ends_on"])
        while label <= end:
            exception = exceptions.get(label.isoformat())
            windows = (
                exception["segments"]
                if exception is not None
                else (
                    calendar["segments"]
                    if label.weekday() in calendar["weekdays"]
                    else []
                )
            )
            converted = []
            for window in windows:
                opened = resolve_local(label, window["open"], zone)
                closed = resolve_local(label, window["close"], zone)
                if opened >= closed or previous is not None and opened < previous:
                    raise ValueError(
                        "segments/session envelopes overlap or reverse in UTC"
                    )
                previous = closed
                converted.append(
                    {
                        "opens_at": timestamp_text(opened),
                        "closes_at": timestamp_text(closed),
                    }
                )
                count += 1
                if count > 50000:
                    raise ValueError("schedule exceeds 50,000 segments")
            records.append(
                {
                    "calendar": calendar["id"],
                    "session": label.isoformat(),
                    "segments": converted,
                    "reason": (
                        exception["reason"] if exception is not None else "weekly"
                    ),
                }
            )
            label += dt.timedelta(days=1)
    return records


def build_calendar(definition):
    normalized = compile_schedule(definition)
    records = [
        load_zone(key)
        for key in sorted({item["timezone"] for item in normalized["calendars"]})
    ]
    zones = {record["key"]: decode_zone(record) for record in records}
    return _document(normalized, records, materialize(normalized, zones))


def _document(definition, zones, sessions):
    result = {
        "format": FORMAT,
        "definition": definition,
        "zones": zones,
        "sessions": sessions,
    }
    result["sha256"] = digest(result)
    bounded_json(result)
    return result


def verify_calendar(document):
    bounded_json(document)
    fields(document, "format definition zones sessions sha256", "calendar document")
    if document["format"] != FORMAT:
        raise ValueError("unsupported calendar format")
    normalized = compile_schedule(document["definition"])
    records = document["zones"]
    expected = sorted({item["timezone"] for item in normalized["calendars"]})
    if not isinstance(records, list) or len(records) != len(expected):
        raise ValueError("calendar timezone inventory mismatch")
    zones = {}
    for record in records:
        zone = decode_zone(record)
        if zone.key in zones:
            raise ValueError("duplicate timezone entity")
        zones[zone.key] = zone
    if [record["key"] for record in records] != expected:
        raise ValueError("calendar timezone inventory/order mismatch")
    if sum(len(record["tzif_base64"]) for record in records) > 3 * 1024 * 1024:
        raise ValueError("calendar timezone inventory exceeds limit")
    rebuilt = _document(normalized, records, materialize(normalized, zones))
    if canonical(document) != canonical(rebuilt):
        raise ValueError("calendar differs from regenerated schedule or digest")
    return copy.deepcopy(rebuilt), zones
