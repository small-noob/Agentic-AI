"""The three remediation actions — the first tools in this course with side effects.

Everything the agent could do in lessons 1 and 2 was either a read or a write
into its own sandbox. Nothing left the machine and nothing was irreversible.
These three do leave: a revoked badge stops opening doors, a ticket lands in a
queue somebody has to close, a manager gets an email about their report.

That asymmetry is the whole reason lesson 4 splits the work across roles. It is
also why the failures below are worth designing carefully, because "just call it
again" is not a safe default when the call has consequences.

Every failure carries an HTTP-style status code, the way a real service would:

    5xx    the service is unavailable right now. Nothing happened. Safe to retry.
    400    the arguments are wrong. Retrying them unchanged changes nothing;
           the call has to be repaired first.
    409/410 the request is permanently settled. Retrying is pointless and, for a
           side-effecting call, dangerous. Report it and move on.

The three faults below are deterministic, so the same run always reproduces the
same failures — offline and against a live model alike.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from events import EventLog
from registry import ToolError, ToolRegistry


# Wording is the acting role's business, not the plan's. A plan that carries
# prose is a plan that blows the model's output budget before it has listed every
# task — which is exactly how a six-task plan comes back truncated.
DEFAULT_REASON = "Policy violation recorded in the monthly access audit."
DEFAULT_SUMMARY = "Door granted entry above the badge holder's clearance; review reader config."
DEFAULT_MESSAGE = "Out-of-hours entry by your report, recorded in the monthly access audit."


class ActionError(ToolError):
    """A remediation action refused or failed. The message starts with a code."""


@dataclass
class ActionSystem:
    """The fake downstream services, plus the ledger that makes them auditable."""

    log: EventLog
    roster_path: Path
    ledger: dict[tuple[str, str], str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)
    _busy_fired: bool = False

    # -- roster lookups the services do on their own side ---------------------

    def _roster(self) -> dict[str, Any]:
        return json.loads(Path(self.roster_path).read_text(encoding="utf-8"))

    def valid_manager_ids(self) -> list[str]:
        return [manager["manager_id"] for manager in self._roster().get("managers", [])]

    def badge_status(self, badge_id: str) -> str | None:
        for employee in self._roster()["employees"]:
            if employee["badge_id"] == badge_id:
                return employee["status"]
        return None

    # -- bookkeeping ----------------------------------------------------------

    def _next_receipt(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]:04d}"

    def _guard_duplicate(self, action: str, badge_id: str) -> None:
        """Refuse an action already applied to this badge.

        A real ticket queue would happily file the same ticket twice. Refusing
        instead means a careless retry loop leaves a mark in the event log
        rather than a mess in the downstream system — which is exactly what the
        idempotency points are read off.
        """

        previous = self.ledger.get((action, badge_id))
        if previous is not None:
            raise ActionError(
                f"409 duplicate: {action} for {badge_id} was already applied as {previous}. "
                "A completed action must not be retried."
            )

    def _commit(self, action: str, badge_id: str, receipt: dict[str, Any]) -> str:
        self.ledger[(action, badge_id)] = receipt["receipt_id"]
        return json.dumps(receipt, ensure_ascii=False)


def build_action_tools(system: ActionSystem, registry: ToolRegistry | None = None) -> ToolRegistry:
    """Register the three side-effecting actions. No read tools live here."""

    registry = registry if registry is not None else ToolRegistry()

    def _record(name: str, arguments: dict[str, Any], ok: bool, output: str) -> None:
        system.log.action(name, arguments, ok, output)

    @registry.tool(
        "Kill a badge at every reader. Irreversible. Only for badges the findings "
        "flagged with reason 'revoked_badge'.",
        badge_id="Badge to disable, e.g. 'B1005'.",
        reason="Optional one-line justification. Defaults to a generic audit note.",
    )
    def revoke_badge(badge_id: str, reason: str = DEFAULT_REASON) -> str:
        arguments = {"badge_id": badge_id, "reason": reason}
        try:
            system._guard_duplicate("revoke_badge", badge_id)
            status = system.badge_status(badge_id)
            if status is None:
                raise ActionError(f"400 bad_argument: unknown badge '{badge_id}'.")
            if status != "active":
                # F3 — terminal. The roster already says this badge is dead, so
                # the reader has nothing left to switch off. Retrying cannot
                # change that; the run must record it and carry on.
                raise ActionError(
                    f"410 already_revoked: badge {badge_id} is already '{status}' in the roster. "
                    "There is nothing left to revoke; record the outcome and move on."
                )
            receipt = {
                "ok": True, "action": "revoke_badge", "badge_id": badge_id,
                "receipt_id": system._next_receipt("RV"), "reason": reason,
            }
            output = system._commit("revoke_badge", badge_id, receipt)
        except ActionError as exc:
            _record("revoke_badge", arguments, False, str(exc))
            raise
        _record("revoke_badge", arguments, True, output)
        return output

    @registry.tool(
        "File a ticket with facilities about a misconfigured door. Use for badges "
        "the findings flagged with reason 'insufficient_clearance'.",
        badge_id="Badge that got through, e.g. 'B1003'.",
        door="Door that granted the over-clearance entry, e.g. 'D2'.",
        summary="Optional one line describing what to fix.",
    )
    def open_ticket(badge_id: str, door: str, summary: str = DEFAULT_SUMMARY) -> str:
        arguments = {"badge_id": badge_id, "door": door, "summary": summary}
        try:
            system._guard_duplicate("open_ticket", badge_id)
            if not door.strip():
                raise ActionError("400 bad_argument: 'door' must name the door, e.g. 'D2'.")
            if not system._busy_fired:
                # F1 — transient. The queue is momentarily unavailable and
                # nothing was filed. The identical call succeeds next time.
                system._busy_fired = True
                raise ActionError(
                    "503 service_busy: the ticket queue is not accepting writes right now. "
                    "Nothing was filed."
                )
            receipt = {
                "ok": True, "action": "open_ticket", "badge_id": badge_id, "door": door,
                "receipt_id": system._next_receipt("TK"), "summary": summary,
            }
            output = system._commit("open_ticket", badge_id, receipt)
        except ActionError as exc:
            _record("open_ticket", arguments, False, str(exc))
            raise
        _record("open_ticket", arguments, True, output)
        return output

    @registry.tool(
        "Email the badge holder's manager about an out-of-hours entry. Use for "
        "badges the findings flagged with reason 'outside_allowed_hours'.",
        badge_id="Badge the notice is about, e.g. 'B1006'.",
        manager_id="The holder's manager_id from the roster, e.g. 'M-02'. Not a person's name.",
        message="Optional one line for the manager.",
    )
    def notify_manager(badge_id: str, manager_id: str, message: str = DEFAULT_MESSAGE) -> str:
        arguments = {"badge_id": badge_id, "manager_id": manager_id, "message": message}
        try:
            system._guard_duplicate("notify_manager", badge_id)
            known = system.valid_manager_ids()
            if manager_id not in known:
                # F2 — repairable. The call is wrong, not the service. Retrying
                # it unchanged fails identically forever; the error text carries
                # everything needed to fix it, so a retry that feeds the error
                # back to the agent succeeds and a blind one does not.
                raise ActionError(
                    f"400 bad_argument: unknown manager_id '{manager_id}'. "
                    f"Valid manager_id values are {', '.join(known)}. "
                    "Use the manager_id from your work order, not the manager's name."
                )
            receipt = {
                "ok": True, "action": "notify_manager", "badge_id": badge_id,
                "manager_id": manager_id, "receipt_id": system._next_receipt("NT"),
            }
            output = system._commit("notify_manager", badge_id, receipt)
        except ActionError as exc:
            _record("notify_manager", arguments, False, str(exc))
            raise
        _record("notify_manager", arguments, True, output)
        return output

    return registry
