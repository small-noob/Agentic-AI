#!/usr/bin/env python3
"""CLI for the lesson 4 harness: roles, plans and retries.

    --mode single     one agent holding every tool (the lesson 2 shape)
    --mode pipeline   part 1: investigator -> remediator, fixed workflow
    --mode plan       part 2: investigator -> planner -> execute, no retries
    --mode full       part 3: the same, with verification and a retry policy
    --mode compare    single vs full, on the same denominator
    --mode sandbox    lesson 2's red team, rerun as a regression gate
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import lesson2  # noqa: F401  (appends 02Tools to sys.path; see lesson2.py)

from actions import ActionSystem
from events import EventLog
from grader import Grade, grade_run
from mock_client import ScriptedMockClient
from redteam import build_attack_workspace, run_attacks, run_legitimate
from roles import (
    INVESTIGATOR,
    PLANNER,
    ROLE_SPECS,
    SINGLE,
    RoleAgent,
    RunContext,
    build_all_tools,
    planner_input,
    skills_index_for,
)
from sandbox import resolve_safe_path
from skill_loader import discover_skills
from task import SKILLS_DIR, TASK_PROMPT, WORKSPACE_ROOT
from zhipu_client import DEFAULT_MODEL, ZhipuClient


def load_implementation(implementation: str):
    """Return the module holding the six harness functions.

    The reference (``harness.py``) is not part of the student package, so asking
    for it there is a clear error rather than an import traceback.
    """

    if implementation == "starter":
        import starter_harness

        return starter_harness
    try:
        import harness
    except ModuleNotFoundError:
        raise SystemExit(
            "harness.py (the reference implementation) is not part of this package. "
            "Run with --implementation starter, which is the default."
        ) from None
    return harness


def build_context(impl, *, model: str, max_steps: int, skills_dir: Path) -> RunContext:
    log = EventLog()
    return RunContext(
        workspace=WORKSPACE_ROOT,
        actions=ActionSystem(log=log, roster_path=WORKSPACE_ROOT / "employees.json"),
        log=log,
        skills=discover_skills(skills_dir),
        validate_plan=impl.validate_plan,
        model=model,
        max_steps=max_steps,
    )


# ---------------------------------------------------------------------------
# The four flows. Composition only — every decision lives in the harness module.
# ---------------------------------------------------------------------------

def flow_single(client, ctx: RunContext) -> dict[str, Any]:
    """The baseline, wired by hand.

    It does not go through ``spawn`` on purpose: this run is what motivates
    TODO 1, so it has to work before TODO 1 exists. Note the one thing missing
    compared with a real spawn — nothing narrows the registry, because holding
    every tool at once is the whole point of the baseline.
    """

    spec = ROLE_SPECS[SINGLE]
    registry = build_all_tools(ctx)
    agent = RoleAgent(
        client, registry, spec.make_verifier(ctx), spec.template,
        skill_index=skills_index_for(spec, ctx.skills),
        model=ctx.model, max_steps=ctx.max_steps,
    )
    ctx.log.spawn(SINGLE, TASK_PROMPT, registry.names())
    ctx.log.agent_done(SINGLE, agent.run(TASK_PROMPT))
    return {}


def flow_pipeline(client, ctx: RunContext, impl) -> dict[str, Any]:
    impl.run_pipeline(client, ctx)
    return {}


def flow_plan(client, ctx: RunContext, impl, *, max_attempts: int) -> dict[str, Any]:
    investigation = impl.spawn(client, INVESTIGATOR, TASK_PROMPT, ctx)
    ctx.findings = investigation.answer
    if ctx.findings is None:
        print("The investigator produced no findings; nothing to plan.")
        return {}

    planning = impl.spawn(client, PLANNER, planner_input(ctx.findings), ctx)
    plan = planning.answer
    if plan is None:
        print("The planner produced no plan; nothing to execute.")
        return {}

    statuses = impl.execute_plan(client, plan, ctx, max_attempts=max_attempts)
    return {"plan": plan, "statuses": statuses}


FLOW_MODES = {
    "single": lambda client, ctx, impl: flow_single(client, ctx),
    "pipeline": lambda client, ctx, impl: flow_pipeline(client, ctx, impl),
    "plan": lambda client, ctx, impl: flow_plan(client, ctx, impl, max_attempts=1),
    "full": lambda client, ctx, impl: flow_plan(client, ctx, impl, max_attempts=3),
}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_trace(log: EventLog) -> None:
    for event in log.events:
        kind = event["kind"]
        if kind == "spawn":
            print(f"\n--- spawn {event['role']} --- tools: {', '.join(event['tools'])}")
        elif kind == "agent_done":
            for step in event["steps"]:
                print(f"  [{event['role']} {step['index']}] {step['model_text'].strip()}")
                if step["observation"]:
                    observation = step["observation"]
                    if len(observation) > 220:
                        observation = observation[:220] + " ..."
                    print(f"      Observation: {observation}")
        elif kind == "action":
            mark = "ok " if event["ok"] else "ERR"
            print(f"  <{mark}> {event['action']}({event['arguments'].get('badge_id', '?')}) "
                  f"-> {event['output'][:110]}")
        elif kind == "verify_fail":
            tag = "retryable" if event["retryable"] else "TERMINAL"
            print(f"  !! verify failed [{tag}] {event['task_id']} attempt {event['attempt']}: "
                  f"{event['reasons'][0][:140]}")
        elif kind == "task_done":
            print(f"  == {event['task_id']}: {event['status']}")


def print_grade(label: str, grade: Grade) -> None:
    status = "PASS" if grade.passed else "FAIL"
    print(f"\n[{label}] {status} — {grade.score}/{grade.total}")
    for item in grade.items:
        mark = "ok" if item.passed else "!!"
        print(f"  {mark} {item.name:<12} {item.score}/{item.total}")
        for line in item.feedback:
            print(f"       - {line}")


def run_mode(mode: str, args, impl) -> dict[str, Any]:
    print(f"\n=== {mode.upper()} ===")
    client = ScriptedMockClient() if args.offline else ZhipuClient.from_env()
    ctx = build_context(impl, model=args.model, max_steps=args.max_steps,
                        skills_dir=args.skills_dir)

    outcome = FLOW_MODES[mode](client, ctx, impl)
    print_trace(ctx.log)

    grade = grade_run(
        ctx.log,
        mode=mode,
        plan=outcome.get("plan"),
        findings=ctx.findings,
        validate_plan=impl.validate_plan,
    )
    print_grade(mode, grade)
    return {
        "mode": mode,
        "findings": ctx.findings,
        "plan": outcome.get("plan"),
        "statuses": outcome.get("statuses"),
        "grade": asdict(grade),
        "events": ctx.log.events,
    }


def run_sandbox_check() -> dict[str, Any]:
    print("\n=== SANDBOX RED TEAM (regression from lesson 2) ===")
    with tempfile.TemporaryDirectory() as tmp:
        root = build_attack_workspace(Path(tmp))
        attacks = run_attacks(resolve_safe_path, root)
        legitimate = run_legitimate(resolve_safe_path, root)
    for row in attacks:
        print(f"  [{'blocked' if row['blocked'] else 'ESCAPED':>7}] {row['attack']:<18} {row['detail']}")
    print("  --- these must still be allowed ---")
    for row in legitimate:
        print(f"  [{'allowed' if row['allowed'] else 'REFUSED':>7}] {row['case']:<18} {row['detail']}")
    ok = all(row["blocked"] for row in attacks) and all(row["allowed"] for row in legitimate)
    print(f"\n[SANDBOX] {'PASS' if ok else 'FAIL'}")
    return {"attacks": attacks, "legitimate": legitimate, "passed": ok}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("single", "pipeline", "plan", "full", "compare", "sandbox"),
        default="full",
    )
    parser.add_argument("--offline", action="store_true", help="Use the scripted mock, no API calls.")
    parser.add_argument("--model", default=os.getenv("ZAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-steps", type=int, default=14)
    parser.add_argument(
        "--implementation",
        choices=("starter", "solution"),
        default="starter",
        help="Your harness (the default), or the reference if you have it.",
    )
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR)
    parser.add_argument("--trace-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.max_steps <= 40:
        raise SystemExit("--max-steps must be between 1 and 40")

    run_data: dict[str, Any] = {"mode": args.mode, "offline": args.offline,
                                "implementation": args.implementation}

    if args.mode == "sandbox":
        run_data["sandbox"] = run_sandbox_check()
    else:
        impl = load_implementation(args.implementation)
        modes = ("single", "full") if args.mode == "compare" else (args.mode,)
        try:
            for mode in modes:
                run_data[mode] = run_mode(mode, args, impl)
        except NotImplementedError as exc:
            print(f"\nYour harness is incomplete: {exc}")
            run_data["error"] = str(exc)

    if args.trace_out:
        args.trace_out.parent.mkdir(parents=True, exist_ok=True)
        args.trace_out.write_text(
            json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nTrace saved to: {args.trace_out}")


if __name__ == "__main__":
    main()
