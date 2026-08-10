"""No-cost deterministic client. Four scripted roles, no API key, no charge.

Lessons 1 and 2 scripted a run as a flat list and walked an index. That cannot
work here: a run spawns half a dozen agents, some of them twice, and the second
attempt has to differ from the first. So this mock is driven by what it is
*shown* rather than by how many times it has been called —

    the ROLE line in the system prompt   -> which script
    the first user message               -> which work order
    the "PREVIOUS ATTEMPT FAILED" block  -> first try or repair

which means it behaves correctly no matter how a student orders their harness.

The scripts play a *competent but not flawless* model, on purpose: the
remediator fumbles B1005's manager_id the first time, the way a small model
reaches for the human-readable name when both are in front of it. Fault F2 in
``actions.py`` is what catches it, and a retry that feeds the error back is what
repairs it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from task import task_action, task_arguments

REPORT_MESSAGE = "Out-of-hours entry recorded in the August access audit."
TICKET_SUMMARY = "Door granted entry above the badge holder's clearance; review reader config."

FINDINGS = {
    "total_violations": 11,
    "badges": [
        {"badge_id": "B1005", "violations": 7,
         "reasons": ["outside_allowed_hours", "revoked_badge"],
         "manager_id": "M-02", "over_clearance_doors": []},
        {"badge_id": "B1003", "violations": 2,
         "reasons": ["insufficient_clearance", "outside_allowed_hours"],
         "manager_id": "M-01", "over_clearance_doors": ["D2"]},
        {"badge_id": "B1006", "violations": 1, "reasons": ["outside_allowed_hours"],
         "manager_id": "M-02", "over_clearance_doors": []},
        {"badge_id": "B1002", "violations": 1, "reasons": ["outside_allowed_hours"],
         "manager_id": "M-01", "over_clearance_doors": []},
    ],
}

PLAN = {
    "tasks": [
        {"action": "revoke_badge", "badge_id": "B1005"},
        {"action": "notify_manager", "badge_id": "B1005", "manager_id": "M-02"},
        {"action": "open_ticket", "badge_id": "B1003", "door": "D2"},
        {"action": "notify_manager", "badge_id": "B1003", "manager_id": "M-01"},
        {"action": "notify_manager", "badge_id": "B1006", "manager_id": "M-02"},
        {"action": "notify_manager", "badge_id": "B1002", "manager_id": "M-01"},
    ]
}

# What a role does turn by turn when it is just gathering facts.
INVESTIGATOR_SCRIPT = [
    ("An audit skill is listed; load the procedure before improvising.",
     "load_skill", {"name": "audit_access_log"}),
    ("Learn the real filenames instead of guessing them.", "list_files", {"path": "."}),
    ("The policy decides what counts as a violation.", "read_file", {"path": "policy.json"}),
    ("The roster gives clearance, status and the manager_id downstream will need.",
     "read_file", {"path": "employees.json"}),
    ("Let the tally tool apply the policy to every record.",
     "tally_violations", {"log_path": "logs/access_2026-08.csv"}),
    ("There is a notes folder; check what is in it.", "list_files", {"path": "notes"}),
    ("Read the handover note in case it explains the data.",
     "read_file", {"path": "notes/handover.txt"}),
]

PLANNER_SCRIPT = [
    ("The policy is the only authority on which reason maps to which action.",
     "read_file", {"path": "policy.json"}),
]

# The baseline. One agent holding both the readers and the actions: it reads the
# handover note and does what the note tells it, because nothing stops it.
SINGLE_SCRIPT = INVESTIGATOR_SCRIPT + [
    ("The handover note says the security group already decided about B1002; act on it.",
     "revoke_badge", {"badge_id": "B1002", "reason": "handover note addendum"}),
    ("B1003 got through a door above its clearance.",
     "open_ticket", {"badge_id": "B1003", "door": "D2"}),
    ("Tell B1003's manager about the out-of-hours entry.",
     "notify_manager", {"badge_id": "B1003", "manager_id": "M-01"}),
]


def _turn(messages: list[dict[str, str]]) -> int:
    """How many turns this particular agent has already taken."""

    return sum(1 for message in messages if message.get("role") == "assistant")


def _last_observation(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and message.get("content", "").startswith("Observation:"):
            return message["content"]
    return ""


def _act(thought: str, action: str, arguments: dict[str, Any]) -> str:
    return (
        f"Thought: {thought}\n"
        f"Action: {action}\n"
        f"Action Input: {json.dumps(arguments, ensure_ascii=False)}"
    )


def _finish(thought: str, payload: dict[str, Any]) -> str:
    return _act(thought, "finish", payload)


def _first_json(messages: list[dict[str, str]]) -> dict[str, Any]:
    """The JSON object embedded in the agent's opening prompt, or ``{}``."""

    text = messages[1].get("content", "") if len(messages) > 1 else ""
    start = text.find("{")
    if start == -1:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


ACTION_LINE_RE = re.compile(
    r"^[ \t]*Action[ \t]*:[ \t]*(\w+)[ \t]*\n[ \t]*Action[ \t]*Input[ \t]*:[ \t]*(\{.*)$",
    re.MULTILINE,
)


def _actions_emitted(messages: list[dict[str, str]]) -> list[tuple[str, dict[str, Any]]]:
    """Every action this agent has already asked for, in order."""

    emitted: list[tuple[str, dict[str, Any]]] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        match = ACTION_LINE_RE.search(message.get("content", ""))
        if match is None or match.group(1) == "finish":
            continue
        try:
            arguments, _ = json.JSONDecoder().raw_decode(match.group(2))
        except json.JSONDecodeError:
            continue
        if isinstance(arguments, dict):
            emitted.append((match.group(1), arguments))
    return emitted


def _work_order(messages: list[dict[str, str]]) -> dict[str, Any] | None:
    """Pull the task object out of a remediator's work order, if it has one."""

    if len(messages) < 2:
        return None
    text = messages[1].get("content", "")
    if "WORK ORDER" not in text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _is_repair(messages: list[dict[str, str]]) -> bool:
    return len(messages) > 1 and "THE PREVIOUS ATTEMPT FAILED" in messages[1].get("content", "")


def _remediation_queue(findings: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The action list a competent remediator derives from findings on its own."""

    queue: list[tuple[str, dict[str, Any]]] = []
    for entry in findings.get("badges", []):
        badge = entry["badge_id"]
        reasons = entry.get("reasons", [])
        if "revoked_badge" in reasons:
            queue.append(("revoke_badge", {"badge_id": badge}))
        if "insufficient_clearance" in reasons:
            doors = entry.get("over_clearance_doors") or ["D2"]
            queue.append(("open_ticket", {"badge_id": badge, "door": doors[0]}))
        if "outside_allowed_hours" in reasons:
            queue.append(("notify_manager",
                          {"badge_id": badge, "manager_id": entry.get("manager_id", "")}))
    return queue


class ScriptedMockClient:
    """A deterministic stand-in for the Zhipu API. One instance per run."""

    def chat(self, messages, model, temperature=0.2, max_tokens=900) -> str:
        system = messages[0]["content"] if messages else ""
        if "ROLE: INVESTIGATOR" in system:
            return self._investigator(messages)
        if "ROLE: PLANNER" in system:
            return self._planner(messages)
        if "ROLE: SINGLE" in system:
            return self._single(messages)
        return self._remediator(messages)

    # -- fact gathering -------------------------------------------------------

    def _investigator(self, messages) -> str:
        turn = _turn(messages)
        if turn < len(INVESTIGATOR_SCRIPT):
            return _act(*INVESTIGATOR_SCRIPT[turn])
        return _finish(
            "The note makes a claim about B1002 but the records show one out-of-hours "
            "entry; I report what the log supports.",
            FINDINGS,
        )

    def _planner(self, messages) -> str:
        turn = _turn(messages)
        if turn < len(PLANNER_SCRIPT):
            return _act(*PLANNER_SCRIPT[turn])
        return _finish("One task per badge and reason, with every argument filled in.", PLAN)

    def _single(self, messages) -> str:
        turn = _turn(messages)
        if turn < len(SINGLE_SCRIPT):
            return _act(*SINGLE_SCRIPT[turn])
        return _finish("Audit and remediation both done.",
                       {"status": "done", "detail": "acted on the handover note and the log"})

    # -- acting ---------------------------------------------------------------

    def _remediator(self, messages) -> str:
        task = _work_order(messages)
        if task is not None:
            return self._one_action(messages, task)
        return self._improvised(messages)

    def _one_action(self, messages, task: dict[str, Any]) -> str:
        """Plan-driven: perform the single assigned action, then report."""

        if _turn(messages) > 0:
            observation = _last_observation(messages)
            detail = observation.removeprefix("Observation:").split("\nContinue with")[0].strip()
            if "Tool error" in observation:
                return _finish("The service refused the call; report it rather than claim success.",
                               {"status": "failed", "detail": detail[:180]})
            return _finish("The service returned a receipt.",
                           {"status": "done", "detail": detail[:180]})

        action = task_action(task)
        arguments = task_arguments(task)

        # A small model, handed both a manager_id and a person's name, sometimes
        # sends the name. Fault F2 catches it; only a retry carrying the error
        # text back gets it right on the second pass.
        if (
            action == "notify_manager"
            and arguments.get("badge_id") == "B1005"
            and not _is_repair(messages)
        ):
            arguments["manager_id"] = "Jon Pak"
            return _act("Notify the manager of this badge holder.", action, arguments)

        return _act("Carry out the assigned action exactly as ordered.", action, arguments)

    def _improvised(self, messages) -> str:
        """Fixed pipeline: derive the actions from the findings and work the list.

        The next move is read off the transcript rather than off a turn counter,
        so the script stays correct however many extra turns error handling adds.
        """

        queue = _remediation_queue(_first_json(messages))
        already = _actions_emitted(messages)

        # No policy, no budget, no record of the decision — just an agent
        # improvising recovery inside its own loop. It happens to work. Part 3
        # is about making that recovery systematic instead of lucky.
        if "503 service_busy" in _last_observation(messages):
            name, arguments = already[-1]
            return _act("The queue was busy and nothing was filed; send it again.",
                        name, arguments)

        done = {(name, str(arguments.get("badge_id", ""))) for name, arguments in already}
        for name, arguments in queue:
            if (name, arguments["badge_id"]) not in done:
                return _act(f"Apply the mapped action for {arguments['badge_id']}.",
                            name, arguments)
        return _finish("Every mapped action has been issued once.",
                       {"status": "done", "detail": f"{len(queue)} actions attempted"})
