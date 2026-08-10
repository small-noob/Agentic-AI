"""Did the task actually happen? Ask the world, not the agent.

An agent that finishes with ``{"status": "done"}`` has told you what it believes.
The only evidence that a badge was really revoked is a receipt from the service
that revokes badges — which is in the event log, because ``actions.py`` writes
one entry per call whether it succeeded or not.

So verification here never reads the agent's answer. It reads the side effects
recorded since the attempt began. Given to you; TODO 3 is the loop that uses it.
"""

from __future__ import annotations

import json
from typing import Any

from events import EventLog
from task import task_action, task_badge


def actions_since(log: EventLog, since_seq: int) -> list[dict[str, Any]]:
    """Action events recorded at or after ``since_seq``, oldest first."""

    return [
        event for event in log.events
        if event["kind"] == "action" and event["seq"] >= since_seq
    ]


def verify_task(task: dict[str, Any], log: EventLog, since_seq: int) -> list[str]:
    """Return the reasons this task is not done. Empty list means done.

    A task is done when the log holds a successful call to the task's action,
    for the task's badge, carrying a receipt id.
    """

    wanted_action, wanted_badge = task_action(task), task_badge(task)
    if not wanted_action or not wanted_badge:
        return ["the task itself is malformed: it needs an action and a badge_id"]

    for event in actions_since(log, since_seq):
        if not event["ok"]:
            continue
        if event["action"] != wanted_action:
            continue
        if str(event["arguments"].get("badge_id", "")) != wanted_badge:
            continue
        try:
            receipt = json.loads(event["output"])
        except json.JSONDecodeError:
            return [f"{wanted_action} returned something that is not a receipt"]
        if not receipt.get("receipt_id"):
            return [f"{wanted_action} returned a receipt with no receipt_id"]
        return []

    attempted = [
        f"{event['action']}({event['arguments'].get('badge_id', '?')}) -> {event['output'][:90]}"
        for event in actions_since(log, since_seq)
    ]
    detail = "; ".join(attempted) if attempted else "no action was called at all"
    return [f"no successful {wanted_action} for {wanted_badge}. What happened: {detail}"]


def last_error(log: EventLog, since_seq: int) -> str:
    """The newest failed-action message since ``since_seq``, or ''.

    This is the text a retry feeds back to the agent. The services are written
    so that it always contains enough to repair a repairable call — which is
    exactly why a retry loop that throws it away cannot recover from F2.
    """

    for event in reversed(actions_since(log, since_seq)):
        if not event["ok"]:
            return str(event["output"])
    return ""
