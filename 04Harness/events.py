"""The run log: one structured record per thing the harness did.

Lesson 1 graded off the ``trace`` its single loop returned. Lesson 2 graded off
``ToolRegistry.history``. Both are per-agent: they answer "what did *this* agent
do". A harness runs several agents, retries some of them, and has to
answer questions no single registry can: which roles ran, what each role was
allowed to see, how many attempts a task took, which failure was terminal.

So lesson 4 keeps its own event log, and the grader reads that. Everything
written here is also what ``--trace-out`` saves, which makes a run replayable.

This module is given to you. You will call ``log.spawn`` / ``log.agent_done``
from TODO 1, and ``log.attempt`` / ``log.verify_fail`` / ``log.task_done`` from
TODO 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EventLog:
    events: list[dict[str, Any]] = field(default_factory=list)

    # -- writing -------------------------------------------------------------

    def record(self, kind: str, **fields: Any) -> dict[str, Any]:
        event = {"seq": len(self.events), "kind": kind, **fields}
        self.events.append(event)
        return event

    def spawn(self, role: str, prompt: str, tools: list[str]) -> None:
        """Announce a fresh sub-agent, its input, and the tools it may use.

        ``tools`` is the evidence for the role-isolation grade: a remediator
        that can see ``read_file`` is not isolated, whatever it went on to do.
        """

        self.record("spawn", role=role, prompt=prompt, tools=sorted(tools))

    def agent_done(self, role: str, result: Any) -> None:
        """Store what the sub-agent said and saw, so its exposure is auditable."""

        self.record(
            "agent_done",
            role=role,
            answer=getattr(result, "answer", None),
            stopped_reason=getattr(result, "stopped_reason", ""),
            steps=[
                {
                    "index": step.index,
                    "model_text": step.model_text,
                    "observation": step.observation,
                }
                for step in getattr(result, "steps", [])
            ],
        )

    def action(self, name: str, arguments: dict[str, Any], ok: bool, output: str) -> None:
        """One call to a side-effecting tool. Emitted by ``actions.py`` itself."""

        self.record("action", action=name, arguments=arguments, ok=ok, output=output)

    def attempt(self, task_id: str, attempt: int) -> None:
        self.record("attempt", task_id=task_id, attempt=attempt)

    def verify_fail(self, task_id: str, attempt: int, reasons: list[str], retryable: bool) -> None:
        self.record(
            "verify_fail", task_id=task_id, attempt=attempt,
            reasons=list(reasons), retryable=retryable,
        )

    def task_done(self, task_id: str, status: str, detail: str = "") -> None:
        """``status`` is 'ok', 'terminal' or 'exhausted'."""

        self.record("task_done", task_id=task_id, status=status, detail=detail)

    def plan_submitted(self, plan: dict[str, Any], problems: list[str]) -> None:
        self.record("plan", plan=plan, problems=list(problems))

    # -- reading (the grader's queries) ---------------------------------------

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["kind"] == kind]

    def roles_spawned(self) -> list[str]:
        return [event["role"] for event in self.of_kind("spawn")]

    def tools_offered_to(self, role: str) -> set[str]:
        """Every tool name any agent of this role was ever handed."""

        return {
            name
            for event in self.of_kind("spawn")
            if event["role"] == role
            for name in event["tools"]
        }

    def text_seen_by(self, role: str) -> str:
        """Everything an agent of this role could read: its input plus its trace.

        This is what the isolation check greps. It deliberately includes the
        prompt the harness built, because handing a role the wrong artefact is
        exactly the mistake worth catching.
        """

        parts = [event["prompt"] for event in self.of_kind("spawn") if event["role"] == role]
        for event in self.of_kind("agent_done"):
            if event["role"] != role:
                continue
            for step in event["steps"]:
                parts.append(step["model_text"] or "")
                parts.append(step["observation"] or "")
        return "\n".join(parts)

    def action_pairs(self, *, only_ok: bool = True) -> list[tuple[str, str]]:
        """``(action_name, badge_id)`` for every action call, in order."""

        return [
            (event["action"], str(event["arguments"].get("badge_id", "")))
            for event in self.of_kind("action")
            if event["ok"] or not only_ok
        ]

    def attempts_for(self, task_id: str) -> int:
        return sum(1 for event in self.of_kind("attempt") if event["task_id"] == task_id)

    def final_status(self, task_id: str) -> str | None:
        for event in reversed(self.of_kind("task_done")):
            if event["task_id"] == task_id:
                return event["status"]
        return None
