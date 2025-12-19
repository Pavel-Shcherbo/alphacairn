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

