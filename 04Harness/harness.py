"""Reference harness. Students write their own in ``starter_harness.py``.

Six functions, three ideas:

    spawn / run_pipeline            a role boundary is a tool subset
    validate_plan / execute_plan    the workflow is data, produced at run time
    classify_failure / run_task_with_retry
                                    a retry policy is a decision, not a loop count

Nothing here knows the expected answer. It knows the shape of a plan, the shape
of a receipt, and what an error code means — which is all a real harness gets.
"""

from __future__ import annotations

import re
from typing import Any

from agent import AgentResult
from roles import (
    ACTION_TOOLS,
    INVESTIGATOR,
    REMEDIATOR,
    ROLE_SPECS,
    RoleAgent,
    RunContext,
    build_all_tools,
    remediator_input_from_findings,
    remediator_input_from_task,
    skills_index_for,
)
from task import (
    MAX_PLAN_TASKS,
    TASK_PROMPT,
    task_action,
    task_arguments,
    task_badge,
    task_id,
)
from verifiers import last_error, verify_task

REQUIRED_TASK_ARGUMENTS = {
    "revoke_badge": {"badge_id"},
    "open_ticket": {"badge_id", "door"},
    "notify_manager": {"badge_id", "manager_id"},
}

TERMINAL_STATUS_CODES = {409, 410}


# ---------------------------------------------------------------------------
# 1 — spawning a role
# ---------------------------------------------------------------------------

def spawn(client, role: str, prompt: str, ctx: RunContext) -> AgentResult:
    """Run one sub-agent under one role and return what it produced.

    Three things make this a boundary rather than a function call:

    * the registry is built fresh and then cut down to the role's tool subset,
      so the agent is not merely told to stay in its lane, it has no other lane;
    * the message list starts empty — no parent transcript is inherited, only
      the ``prompt`` artefact;
    * both facts are written to the event log before the agent runs, because a
      boundary nobody recorded is a boundary nobody can audit.
    """

    spec = ROLE_SPECS[role]

    registry = build_all_tools(ctx)
    registry.tools = {
        name: tool for name, tool in registry.tools.items() if name in spec.tools
    }

    agent = RoleAgent(
        client,
        registry,
        spec.make_verifier(ctx),
        spec.template,
        skill_index=skills_index_for(spec, ctx.skills),
        model=ctx.model,
        max_steps=ctx.max_steps,
    )

    ctx.log.spawn(role, prompt, registry.names())
    result = agent.run(prompt)
    ctx.log.agent_done(role, result)
    return result


def run_pipeline(client, ctx: RunContext) -> AgentResult | None:
    """The fixed two-role workflow: investigate, then remediate.

    The handover is ``result.answer`` — the artefact the investigator produced,
    not the conversation it had getting there. Everything the investigator read,
    including anything persuasive it found in the workspace, stops here.
    """

    investigation = spawn(client, INVESTIGATOR, TASK_PROMPT, ctx)
    ctx.findings = investigation.answer
    if ctx.findings is None:
        return None
    return spawn(client, REMEDIATOR, remediator_input_from_findings(ctx.findings), ctx)


# ---------------------------------------------------------------------------
# 2 — the plan
# ---------------------------------------------------------------------------

def validate_plan(plan: Any, findings: dict[str, Any] | None = None) -> list[str]:
    """Return every reason this plan may not be executed. Empty list means run it.

    A plan arrives from a language model, so it is untrusted input in exactly
    the sense lesson 2's paths were. The checks fall into three groups:

    * *well formed* — ids, known actions, complete arguments;
    * *authorised* — no action on a badge the findings never flagged, no action
      a badge's reasons do not map to, and no argument that contradicts them;
    * *complete* — every action the findings do map to is actually planned.

    The third one is easy to leave out and is the one that bites. A model asked
    for a plan will cheerfully return the first task and stop, and a validator
    that only looks at what is present will wave it through. Silently doing a
    sixth of the work is a worse failure than a malformed plan, because nothing
    downstream notices.
    """

    problems: list[str] = []
    if not isinstance(plan, dict):
        return ["the plan must be a JSON object with a 'tasks' list"]
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return ["'tasks' must be a non-empty list"]
    if len(tasks) > MAX_PLAN_TASKS:
        problems.append(f"{len(tasks)} tasks is more than the {MAX_PLAN_TASKS} allowed")

    allowed: dict[str, set[str]] = {}
    expected_arguments: dict[tuple[str, str], dict[str, str]] = {}
    if isinstance(findings, dict):
        from task import KNOWN_REASONS  # local import keeps the module import-light

        mapping = {
            "revoked_badge": "revoke_badge",
            "insufficient_clearance": "open_ticket",
            "outside_allowed_hours": "notify_manager",
        }
        for entry in findings.get("badges", []):
            if not isinstance(entry, dict):
                continue
            reasons = [r for r in entry.get("reasons", []) if r in KNOWN_REASONS]
            badge = str(entry.get("badge_id"))
            allowed[badge] = {mapping[r] for r in reasons}
            # The findings are the source of truth for these, so a task that
            # disagrees with them is wrong even though it looks complete.
            expected_arguments[(badge, "notify_manager")] = {
                "manager_id": str(entry.get("manager_id", ""))
            }
            doors = entry.get("over_clearance_doors") or []
            if doors:
                expected_arguments[(badge, "open_ticket")] = {"door": str(doors[0])}

    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    for position, task in enumerate(tasks, start=1):
        where = f"task #{position}"
        if not isinstance(task, dict):
            problems.append(f"{where} is not an object")
            continue

        identifier = task_id(task, position)
        if identifier in seen_ids:
            problems.append(f"duplicate task id '{identifier}'")
        seen_ids.add(identifier)
        where = f"task '{identifier}'"

        action = task_action(task)
        if action not in ACTION_TOOLS:
            problems.append(f"{where}: '{action}' is not a remediation action")
            continue

        arguments = task_arguments(task)
        badge_id = task_badge(task)
        if not re.fullmatch(r"B\d{4}", badge_id):
            problems.append(f"{where}: needs a badge_id shaped like B1234")
            continue

        missing = sorted(REQUIRED_TASK_ARGUMENTS[action] - set(arguments))
        if missing:
            problems.append(
                f"{where}: {action} also needs {missing}; the remediator cannot look them up"
            )

        for key, value in expected_arguments.get((badge_id, action), {}).items():
            if value and str(arguments.get(key, "")) != value:
                problems.append(
                    f"{where}: {key} is '{arguments.get(key)}' but the findings say "
                    f"'{value}' for {badge_id}"
                )

        pair = (action, badge_id)
        if pair in seen_pairs:
            problems.append(f"{where}: {action} is already planned for {badge_id}")
        seen_pairs.add(pair)

        if allowed:
            if badge_id not in allowed:
                problems.append(
                    f"{where}: {badge_id} is not in the findings; it may not be acted on"
                )
            elif action not in allowed[badge_id]:
                problems.append(
                    f"{where}: {badge_id}'s reasons do not map to {action}"
                )

    if allowed:
        required = {
            (action, badge_id)
            for badge_id, actions in allowed.items()
            for action in actions
        }
        for action, badge_id in sorted(required - seen_pairs):
            problems.append(
                f"the findings require {action} for {badge_id} and the plan has no task for it"
            )

    return problems


def execute_plan(
    client,
    plan: dict[str, Any],
    ctx: RunContext,
    *,
    max_attempts: int = 1,
) -> dict[str, str]:
    """Run every task in the plan and return ``{task_id: status}``.

    Tasks are independent, so this is a flat loop. ``max_attempts=1`` is the
    plan-only run of part 2; part 3 raises it and the retry policy comes alive.
    A task that ends 'terminal' or 'exhausted' does not stop the others — one
    badge that cannot be revoked is not a reason to leave three managers
    un-notified.
    """

    statuses: dict[str, str] = {}
    for index, task in enumerate(plan.get("tasks", []), start=1):
        # Ids are optional in the plan, so stamp one on before anything logs it.
        stamped = {"id": task_id(task, index), **task}
        statuses[stamped["id"]] = run_task_with_retry(
            client, stamped, ctx, max_attempts=max_attempts
        )
    return statuses


# ---------------------------------------------------------------------------
# 3 — verify and retry
# ---------------------------------------------------------------------------

def classify_failure(error_text: str) -> str:
    """'terminal' if trying again cannot help, otherwise 'retryable'.

    The services speak in status codes on purpose. 409 and 410 mean the request
    is permanently settled — the badge is already dead, the ticket already
    filed. Calling again cannot change that and, for a side-effecting call, is
    how duplicates get created. Everything else is worth one more attempt,
    because the retry carries the error text back to the agent and a 400 with a
    good message is repairable.
    """

    match = re.match(r"\s*(\d{3})\b", error_text or "")
    if match and int(match.group(1)) in TERMINAL_STATUS_CODES:
        return "terminal"
    return "retryable"


def run_task_with_retry(
    client,
    task: dict[str, Any],
    ctx: RunContext,
    *,
    max_attempts: int = 3,
) -> str:
    """Execute one task until it is verified done, permanently failed, or out of tries.

    Returns 'ok', 'terminal' or 'exhausted'.

    Two things separate this from ``for _ in range(3): try_again()``:

    * success is decided by ``verify_task``, which reads the side-effect log
      rather than the agent's own claim;
    * the failure text is fed into the next attempt. Without that, F2 (a wrong
      manager_id) reproduces identically forever — the fix is in the error
      message and nowhere else.
    """

    identifier = task_id(task, 0)
    feedback = ""

    for attempt in range(1, max_attempts + 1):
        since_seq = len(ctx.log.events)
        ctx.log.attempt(identifier, attempt)

        spawn(client, REMEDIATOR, remediator_input_from_task(task, feedback), ctx)

        problems = verify_task(task, ctx.log, since_seq)
        if not problems:
            ctx.log.task_done(identifier, "ok")
            return "ok"

        error = last_error(ctx.log, since_seq)
        kind = classify_failure(error)
        ctx.log.verify_fail(identifier, attempt, problems, retryable=kind == "retryable")

        if kind == "terminal":
            # Nothing to salvage and nothing safe to repeat. Record it as a real
            # outcome and let the rest of the plan continue.
            ctx.log.task_done(identifier, "terminal", error)
            return "terminal"

        feedback = error or "; ".join(problems)

    ctx.log.task_done(identifier, "exhausted", feedback)
    return "exhausted"
