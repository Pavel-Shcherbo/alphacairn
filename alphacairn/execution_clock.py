"""Shared deterministic event instants for explicit and strategy-driven execution."""

import itertools


def timeline_groups(scenario, extras=()):
    from .corporate_model import action_instants

    timeline = list(extras) + list(action_instants(scenario))
    for index, bar in enumerate(scenario["bars"]):
        timeline.extend(
            [(bar["opened_at"], "open", index), (bar["closed_at"], "close", index)]
        )
    for index, command in enumerate(scenario["commands"]):
        timeline.append((command["at"], "command", index))
        if (
            command["action"] == "submit"
            and command["expires_at"] is not None
            and command["expires_at"] <= scenario["ends_at"]
        ):
            timeline.append((command["expires_at"], "expiry", command["id"]))
    for index, quote in enumerate(scenario["fx"]):
        timeline.append((quote["at"], "fx", index))
    timeline.extend(
        [(scenario["starts_at"], "boundary", 0), (scenario["ends_at"], "boundary", 1)]
    )
    timeline.sort(key=lambda item: item[0])
    for at, items in itertools.groupby(timeline, key=lambda item: item[0]):
        groups = {}
        for _, kind, reference in items:
            groups.setdefault(kind, []).append(reference)
        yield at, groups
