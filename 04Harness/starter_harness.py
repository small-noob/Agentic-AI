"""Student starter. Six functions, three TODOs. Everything else is given.

Check your work as you go:

    python3 main.py --mode single   --offline    # watch it fail first
    python3 main.py --mode pipeline --offline    # TODO 1
    python3 main.py --mode plan     --offline    # TODO 2
    python3 main.py --mode full     --offline    # TODO 3
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import re
from typing import Any

import lesson2  # noqa: F401  (appends 02Tools to sys.path; see lesson2.py)

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
from task import MAX_PLAN_TASKS, TASK_PROMPT
from verifiers import last_error, verify_task

# Arguments each action needs. The remediator has no read tools, so anything
# missing here is unavailable to it — permanently.
REQUIRED_TASK_ARGUMENTS = {
    "revoke_badge": {"badge_id"},
    "open_ticket": {"badge_id", "door"},
    "notify_manager": {"badge_id", "manager_id"},
}


# ===========================================================================
# TODO 1 — the role boundary
# ===========================================================================

def spawn(client, role: str, prompt: str, ctx: RunContext) -> AgentResult:
    """TODO 1a — run one sub-agent under one role and return its AgentResult.

    Roughly:

    1.  ``spec = ROLE_SPECS[role]`` — the role's prompt template, tool names,
        whether it gets skills, and how its finish is verified.
    2.  Build a **fresh** registry with ``build_all_tools(ctx)``. It comes back
        holding every tool in the lesson.
    3.  Cut it down to ``spec.tools``. ``registry.tools`` is a plain dict of
        name -> ToolSpec, so this is a dict comprehension. **This line is the
        assignment.** Everything else here is wiring.
    4.  Build the agent:

            RoleAgent(client, registry, spec.make_verifier(ctx), spec.template,
                      skill_index=skills_index_for(spec, ctx.skills),
                      model=ctx.model, max_steps=ctx.max_steps)

    5.  ``ctx.log.spawn(role, prompt, registry.names())`` **before** running,
        then ``result = agent.run(prompt)``, then ``ctx.log.agent_done(role, result)``.

    Two things worth pausing on:

    - Why build a new registry per spawn instead of sharing one? Look at what
      ``ToolRegistry.history`` is used for, and at what ``ctx.actions.ledger``
      is used for. One of those two must be shared across the run and the other
      must not.
    - Why log the tool list at all, when the agent's behaviour is already in the
      trace? Because "it never called read_file" and "it could not call
      read_file" are different claims, and only one of them is a boundary.
    """

    raise NotImplementedError("TODO 1a: implement spawn() in starter_harness.py")


def run_pipeline(client, ctx: RunContext) -> AgentResult | None:
    """TODO 1b — the fixed two-role workflow: investigate, then remediate.

    1.  Spawn ``INVESTIGATOR`` on ``TASK_PROMPT``.
    2.  Its findings are ``result.answer``. Store them on ``ctx.findings`` —
        the planner's verifier reads them later. Return ``None`` if there are
        none.
    3.  Spawn ``REMEDIATOR`` on ``remediator_input_from_findings(ctx.findings)``
        and return that result.

    The single decision here is what crosses between step 1 and step 3. You have
    the investigator's whole ``AgentResult``: its messages, its observations,
    every file it read. Hand over the artefact it produced, not the conversation
    it had — the isolation points are read off exactly that choice, and so is
    what happens to the instruction planted in the workspace.
    """

    raise NotImplementedError("TODO 1b: implement run_pipeline() in starter_harness.py")


# ===========================================================================
# TODO 2 — the plan
# ===========================================================================

def validate_plan(plan: Any, findings: dict[str, Any] | None = None) -> list[str]:
    """TODO 2a — return every reason this plan must not be executed.

    Empty list means "run it". This is called from the planner's finish verifier,
    so anything you return goes back to the model as an Observation to fix —
    write messages you would want to receive.

    A plan is untrusted input, exactly like a path was in lesson 2. Two
    different questions to answer about it:

    **Is it well formed?**
      - ``plan`` is a dict with a non-empty ``tasks`` list, no longer than
        ``MAX_PLAN_TASKS``
      - every task has an id, and no id repeats
      - ``task["action"]`` is one of ``ACTION_TOOLS``
      - ``task["input"]`` is a dict with a ``badge_id`` shaped like ``B1234``
      - it carries every argument in ``REQUIRED_TASK_ARGUMENTS[action]``
      - no ``(action, badge_id)`` pair appears twice — seven violating records
        are still one revoke

    **Is it authorised?** (only when ``findings`` is not None)
      - the badge appears in ``findings["badges"]``
      - the action is one the policy maps from a reason that badge actually has:
        revoked_badge -> revoke_badge, insufficient_clearance -> open_ticket,
        outside_allowed_hours -> notify_manager
      - the arguments agree with the findings. The findings already say which
        manager_id and which door belong to a badge, so a task naming a
        different one is wrong even though nothing is missing.

    **Is it complete?** (also only with ``findings``)
      - every action those reasons map to has a task. Nothing was quietly
        dropped.

    The last two groups are the ones worth thinking about, and they fail in
    opposite directions. A validator that only checks shape will happily execute
    a perfectly well formed plan to revoke a badge that did nothing wrong — and
    it will just as happily accept a plan that contains one task out of six,
    which is the failure nothing downstream will ever notice.

    Careful in the other direction too: a validator that rejects everything
    passes no plan at all, and lesson 2 already showed what that is worth.
    """

    raise NotImplementedError("TODO 2a: implement validate_plan() in starter_harness.py")


def execute_plan(
    client,
    plan: dict[str, Any],
    ctx: RunContext,
    *,
    max_attempts: int = 1,
) -> dict[str, str]:
    """TODO 2b — run every task in the plan; return ``{task_id: status}``.

    The tasks are independent, so this is a flat loop over ``plan["tasks"]``
    calling ``run_task_with_retry(client, task, ctx, max_attempts=max_attempts)``
    and collecting what it returns.

    ``max_attempts`` is 1 for the part-2 run and 3 for part 3 — one function,
    two behaviours, which is why the retry policy lives in the next TODO rather
    than here.

    One decision: a task that fails permanently. Does the rest of the plan stop?
    Ask what that means in this scenario — one badge that cannot be revoked, and
    three managers who then never hear about anything.
    """

    raise NotImplementedError("TODO 2b: implement execute_plan() in starter_harness.py")


# ===========================================================================
# TODO 3 — verify and retry
# ===========================================================================

def classify_failure(error_text: str) -> str:
    """TODO 3a — return 'terminal' if trying again cannot help, else 'retryable'.

    The services in ``actions.py`` answer like an HTTP API: every failure starts
    with a three-digit status code. Read that module's docstring for what the
    codes mean — the classification follows from it, and the point of this
    function is that it is a *policy decision*, not a string match.

    Ask, for each code you might see: if I send this exact request again, can
    the outcome differ? And separately: if the call already had an effect, what
    does sending it again cost?
    """

    raise NotImplementedError("TODO 3a: implement classify_failure() in starter_harness.py")


def run_task_with_retry(
    client,
    task: dict[str, Any],
    ctx: RunContext,
    *,
    max_attempts: int = 3,
) -> str:
    """TODO 3b — execute one task until it is done, permanently failed, or out of tries.

    Return 'ok', 'terminal' or 'exhausted'.

    The loop, per attempt:

    1.  ``since_seq = len(ctx.log.events)`` — remember where this attempt starts,
        so verification only looks at what *this* attempt did.
    2.  ``ctx.log.attempt(task_id, attempt)``.
    3.  Spawn ``REMEDIATOR`` on ``remediator_input_from_task(task, feedback)``.
    4.  ``problems = verify_task(task, ctx.log, since_seq)``. Empty means done:
        log ``ctx.log.task_done(task_id, "ok")`` and return.
    5.  Otherwise get ``last_error(ctx.log, since_seq)``, classify it, and log
        ``ctx.log.verify_fail(task_id, attempt, problems, retryable=...)``.
    6.  Terminal: log ``task_done(task_id, "terminal", error)`` and return.
        Retryable: carry the error into ``feedback`` for the next attempt.
    7.  Out of attempts: log ``task_done(task_id, "exhausted", ...)`` and return.

    Two of those steps are the whole lesson, and both are easy to leave out:

    - Step 4 asks the **log**, not the agent. The agent's own ``finish`` says
      what it believes; only a receipt from the service is evidence. An agent
      that reports ``{"status": "done"}`` after a 503 is not lying, it is wrong.
    - Step 6 carries the error text forward. Fault F2 is a wrong ``manager_id``
      and the fix is written in the error message. A retry that discards it will
      reproduce the identical failure until the budget runs out — which is not a
      retry policy, it is the same mistake three times.
    """

    raise NotImplementedError("TODO 3b: implement run_task_with_retry() in starter_harness.py")
