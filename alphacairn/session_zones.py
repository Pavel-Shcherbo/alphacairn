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


def zone_key(value):
    if (
        not isinstance(value, str)
        or len(value) > 128
        or not re.fullmatch(r"[A-Za-z0-9_+./-]+", value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError("timezone requires a bounded relative IANA key")
    return value


def check_tzif(raw):
    if not isinstance(raw, bytes) or not 44 <= len(raw) <= MAX_ZONE_BYTES:
        raise ValueError("timezone entity exceeds limits or is truncated")

    def block(offset, width):
        if raw[offset : offset + 4] != b"TZif" or offset + 44 > len(raw):
            raise ValueError("invalid TZif header")
        version = raw[offset + 4 : offset + 5]
        if version not in (b"\0", b"2", b"3"):
            raise ValueError("unsupported TZif version")
        ut, std, leap, times, types, chars = struct.unpack_from(">6I", raw, offset + 20)
        if (
            not 1 <= types <= 256
            or times > 20000
            or chars > 65536
            or leap > 2048
            or std not in (0, types)
            or ut not in (0, types)
        ):
            raise ValueError("TZif counts exceed supported bounds")
        end = (
            offset
            + 44
            + times * (width + 1)
            + types * 6
            + chars
            + leap * (width + 4)
            + std
            + ut
        )
        if end > len(raw):
            raise ValueError("truncated TZif block")
        return version, end

    version, end = block(0, 4)
    if version != b"\0":
        other, end = block(end, 8)
        if other != version:
            raise ValueError("TZif header versions disagree")
        if len(raw) - end > 4096:
            raise ValueError("TZif rule tail exceeds limits")
    elif end != len(raw):
        raise ValueError("unexpected TZif v1 tail")
    return raw


def load_zone(key):
    key = zone_key(key)
    for root in zoneinfo.TZPATH:
        path = Path(root).joinpath(*key.split("/"))
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_ZONE_BYTES + 1)
            return zone_record(key, raw, "system")
        except FileNotFoundError:
            pass
    try:
        resource = importlib.resources.files("tzdata.zoneinfo").joinpath(
            *key.split("/")
        )
        with resource.open("rb") as stream:
            raw = stream.read(MAX_ZONE_BYTES + 1)
        return zone_record(key, raw, "tzdata")
    except (ModuleNotFoundError, FileNotFoundError) as error:
        raise ValueError(f"timezone data unavailable for {key}") from error


