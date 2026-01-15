"""Caller-declared settlement dates over portable joint business-day calendars."""

from bisect import bisect_left, bisect_right
import copy

from .instruments import AccountSpec, timestamp, timestamp_text
from .session_calendar import SessionCalendar
from .session_model import day, fields


class SettlementClock:
    def __init__(self, definition, account):
        fields(definition, "version calendar rules", "settlement policy")
        if type(definition["version"]) is not int or definition["version"] != 1:
            raise ValueError("settlement policy requires version 1")
        self.calendar = (
            SessionCalendar(definition["calendar"])
            if definition["calendar"] is not None
            else None
        )
        if self.calendar and self.calendar.definition["instruments"]:
            raise ValueError(
                "settlement calendars use explicit rule bindings, not trading instrument bindings"
            )
        rules = definition["rules"]
        if not isinstance(rules, list) or len(rules) != len(account.instruments):
            raise ValueError(
                "settlement rules must cover every account instrument once"
            )
        self.rules, self.joint = {}, {}
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError("settlement rule requires an object")
            instrument = account.instrument(rule.get("instrument"))
            if instrument.id in self.rules:
                raise ValueError("duplicate settlement instrument rule")
            mode = rule.get("mode")
            if mode == "immediate":
                fields(rule, "instrument mode", "immediate settlement")
            elif mode == "business_days":
                fields(
                    rule,
                    "instrument mode lag calendars trade_date_basis",
                    "business-day settlement",
                )
                lag = rule["lag"]
                if type(lag) is not int or not 0 <= lag <= 10:
                    raise ValueError("settlement lag must be 0–10 business days")
                calendars = rule["calendars"]
                if (
                    not isinstance(calendars, list)
                    or not 1 <= len(calendars) <= 4
                    or any(not isinstance(name, str) for name in calendars)
                    or len(set(calendars)) != len(calendars)
                ):
                    raise ValueError(
                        "settlement requires 1–4 distinct calendars; the first sets local trade date"
                    )
                if rule["trade_date_basis"] not in ("local_fill_date", "session_label"):
                    raise ValueError(
                        "declare local_fill_date or session_label for settlement"
                    )
                if self.calendar is None or not set(calendars) <= set(
                    self.calendar.calendars
                ):
                    raise ValueError(
                        "settlement rule references an unavailable calendar"
                    )
                key = tuple(calendars)
                if key not in self.joint:
                    self.joint[key] = self.build_joint(calendars)
            else:
                raise ValueError("settlement mode must be immediate or business_days")
            self.rules[instrument.id] = copy.deepcopy(rule)
        self.definition = {
            "version": 1,
            "calendar": (
                copy.deepcopy(self.calendar.document) if self.calendar else None
            ),
            "rules": [self.rules[key] for key in sorted(self.rules)],
        }

    def build_joint(self, calendars):
        for name in calendars:
            definition = self.calendar.calendars[name]
            windows = list(definition["segments"])
            for exception in definition["exceptions"]:
                windows.extend(exception["segments"])
            if any(
                window[endpoint]["day_offset"] != 0
                for window in windows
                for endpoint in ("open", "close")
            ):
                raise ValueError(
                    "settlement business windows must stay on their labeled local day"
                )
        common = set(self.calendar.open_labels[calendars[0]])
        for name in calendars[1:]:
            common.intersection_update(self.calendar.open_labels[name])
        labels = sorted(common)
        cutoffs = [
            max(
                timestamp(
                    self.calendar.labels[name, label]["segments"][-1]["closes_at"]
                )
                for name in calendars
            )
            for label in labels
        ]
        if any(left >= right for left, right in zip(cutoffs, cutoffs[1:])):
            raise ValueError("joint settlement cutoffs must increase")
        return labels, cutoffs

    def due(self, instrument, at, session):
        when = timestamp(at)
        rule = self.rules[instrument]
        if rule["mode"] == "immediate":
            return {
                "settles_at": timestamp_text(when),
                "trade_date": None,
                "settlement_date": None,
                "calendar_sha256": None,
                "rule": copy.deepcopy(rule),
            }
        primary = self.calendar.calendars[rule["calendars"][0]]
        zone = self.calendar.zones[primary["timezone"]]
        trade_date = (
            when.astimezone(zone).date().isoformat()
            if rule["trade_date_basis"] == "local_fill_date"
            else day(session).isoformat()
        )
        if (
            not self.calendar.definition["starts_on"]
            <= trade_date
            <= self.calendar.definition["ends_on"]
        ):
            raise ValueError("trade date is outside retained settlement coverage")
        labels, cutoffs = self.joint[tuple(rule["calendars"])]
        index = (
            (bisect_right(labels, trade_date) + rule["lag"] - 1)
            if rule["lag"]
            else bisect_left(labels, trade_date)
        )
        if rule["lag"] == 0:
            while index < len(labels) and cutoffs[index] < when:
                index += 1
        if index >= len(labels):
            raise ValueError("retained settlement calendar does not cover the due date")
        if cutoffs[index] < when:
            raise ValueError(
                "session label implies settlement before fill; review trade-date basis"
            )
        return {
            "settles_at": timestamp_text(cutoffs[index]),
            "trade_date": trade_date,
            "settlement_date": labels[index],
            "calendar_sha256": self.calendar.document["sha256"],
            "rule": copy.deepcopy(rule),
        }


def compile_settlement(value, account, bars):
    clock = SettlementClock(value, account)
    for bar in bars:
        for endpoint in ("opened_at", "closed_at"):
            clock.due(bar["instrument"], bar[endpoint], bar["session"])
    return clock.definition


def settlement_instants(scenario):
    if scenario["version"] != 5:
        return []
    clock = SettlementClock(
        scenario["settlement"], AccountSpec.compile(scenario["account"])
    )
    dues = {
        clock.due(bar["instrument"], bar[endpoint], bar["session"])["settles_at"]
        for bar in scenario["bars"]
        for endpoint in ("opened_at", "closed_at")
    }
    return [
        (due, "settlement", 0)
        for due in sorted(dues)
        if scenario["starts_at"] <= due <= scenario["ends_at"]
    ]
