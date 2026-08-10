"""Last week's exercise, this week's tool.

Counting violations across a month of records *was* the assignment in lesson 2.
Lesson 4 does not grade it, and a small model asked to do it by eye will read the
same file five times and never converge — which is a real finding about small
models, and a waste of a classroom hour.

So the counting is packaged as a tool, the way lesson 2 packaged lesson 1's
calculator. The rules it applies are exactly the ones in ``policy.json``; the
tool is not allowed to know anything the policy does not say.

What it deliberately does **not** do is fill in ``manager_id``. That lives in the
roster, and the investigator has to join it in itself — because the reason it
belongs in the findings at all is that a downstream role cannot look it up, and
that is the one thing about the handover this lesson does want students to see.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from pathlib import Path

from registry import ToolError, ToolRegistry
from sandbox import SandboxError, resolve_safe_path


def tally(policy: dict, roster: dict, log_text: str) -> dict:
    """Apply the policy's violation rules to raw log text. Pure, testable, dull."""

    doors = policy["doors"]
    start = int(policy["allowed_hours"]["start"].split(":")[0])
    end = int(policy["allowed_hours"]["end"].split(":")[0])
    employees = {person["badge_id"]: person for person in roster["employees"]}

    per_badge: dict[str, dict] = defaultdict(
        lambda: {"violations": 0, "reasons": set(), "over_clearance_doors": set()}
    )
    total = 0

    for row in csv.DictReader(io.StringIO(log_text)):
        if row.get("result") != "granted":
            continue  # a denied attempt is the control working, not a violation
        badge_id, door = row["badge_id"], row["door"]
        person = employees.get(badge_id)
        hour = int(row["timestamp"][11:13])

        reasons: list[str] = []
        if person is None or person["status"] != "active":
            reasons.append("revoked_badge")
        if person is not None and person["clearance"] < doors[door]["min_clearance"]:
            reasons.append("insufficient_clearance")
            per_badge[badge_id]["over_clearance_doors"].add(door)
        if hour < start or hour >= end:
            reasons.append("outside_allowed_hours")

        if not reasons:
            continue
        total += 1  # one record is one violation, however many rules fired
        per_badge[badge_id]["violations"] += 1
        per_badge[badge_id]["reasons"].update(reasons)

    return {
        "total_violations": total,
        "per_badge": {
            badge_id: {
                "violations": entry["violations"],
                "reasons": sorted(entry["reasons"]),
                "over_clearance_doors": sorted(entry["over_clearance_doors"]),
            }
            for badge_id, entry in sorted(
                per_badge.items(), key=lambda item: -item[1]["violations"]
            )
        },
    }


def build_audit_tool(root: str | Path, registry: ToolRegistry) -> ToolRegistry:
    root = Path(root).resolve()

    @registry.tool(
        "Apply policy.json's violation rules to an access log and return, per badge, "
        "how many records it violated and which reasons fired. Does not look up "
        "manager_id — read employees.json for that.",
        log_path="Log file relative to the workspace root, e.g. 'logs/access_2026-08.csv'.",
    )
    def tally_violations(log_path: str) -> str:
        try:
            target = resolve_safe_path(root, log_path, must_exist=True)
            policy = json.loads((root / "policy.json").read_text(encoding="utf-8"))
            roster = json.loads((root / "employees.json").read_text(encoding="utf-8"))
        except SandboxError as exc:
            raise ToolError(exc) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError(f"could not load the policy or roster: {exc}") from exc

        try:
            result = tally(policy, roster, target.read_text(encoding="utf-8"))
        except (KeyError, ValueError) as exc:
            raise ToolError(f"the log does not match the expected columns: {exc}") from exc
        return json.dumps(result, ensure_ascii=False)

    return registry
