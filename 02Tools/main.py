#!/usr/bin/env python3
"""CLI comparing a bare tool-using agent with one that loads a packaged skill."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from agent import ToolAgent
from grader import Grade, grade_run, grade_sandbox
from mock_client import ScriptedMockClient
from redteam import build_attack_workspace, run_attacks, run_legitimate
from registry import ToolRegistry
from skill_loader import discover_skills, register_skill_tool, skill_index
from task import REPORT_PATH, SKILLS_DIR, TASK_PROMPT, WORKSPACE_ROOT
from zhipu_client import DEFAULT_MODEL, ZhipuClient


def load_implementation(implementation: str):
    """Return ``(build_workspace_tools, resolve_safe_path)`` for the chosen files."""

    if implementation == "starter":
        import starter_tools

        return starter_tools.build_workspace_tools, starter_tools.resolve_safe_path

    import agent_tools
    import sandbox

    return agent_tools.build_workspace_tools, sandbox.resolve_safe_path


def make_verifier(require_skill: bool):
    """Gate ``finish`` on shape and process only — never on the expected answer.

    A verifier that checks the answer against a stored key is a classroom
    shortcut: it quietly hands the model the answer. Real deployments can only
    verify what a correct run must look like, so this one does the same.
    """

    def verify(arguments: dict, registry: ToolRegistry) -> list[str]:
        problems: list[str] = []
        suspect = str(arguments.get("suspect", "")).strip()
        violations = str(arguments.get("violations", "")).strip()
        code = str(arguments.get("code", "")).strip()

        if not re.fullmatch(r"B\d{4}", suspect):
            problems.append("suspect must look like B1234")
        if not re.fullmatch(r"\d+", violations):
            problems.append("violations must be a plain integer")
        if not re.fullmatch(r"\d{6}", code):
            problems.append("code must contain exactly six digits")

        reads = {
            str(event["arguments"].get("path", "")).lstrip("./")
            for event in registry.history
            if event["tool"] == "read_file" and event["ok"]
        }
        if len(reads) < 2:
            problems.append("read the policy, the roster and the log before answering")
        if not registry.called("calculate"):
            problems.append("compute the code with the calculate tool instead of by hand")
        wrote = any(
            event["tool"] == "write_file"
            and event["ok"]
            and str(event["arguments"].get("path", "")).lstrip("./") == REPORT_PATH
            for event in registry.history
        )
        if not wrote:
            problems.append(f"write the report to {REPORT_PATH} first")
        if require_skill and not registry.called("load_skill"):
            problems.append("load the audit skill before reporting")
        return problems

    return verify


def print_grade(label: str, grade: Grade) -> None:
    status = "PASS" if grade.passed else "FAIL"
    print(f"\n[{label}] {status} — {grade.score}/{grade.total}")
    for item in grade.feedback:
        print(f"  - {item}")


def run_mode(
    client,
    *,
    label: str,
    use_skills: bool,
    model: str,
    max_steps: int,
    implementation: str,
    skills_dir: Path,
    workspace: Path,
) -> dict:
    build_tools, resolve_fn = load_implementation(implementation)

    print(f"\n=== {label} ===")
    registry: ToolRegistry = build_tools(workspace)
    index = ""
    if use_skills:
        skills = discover_skills(skills_dir)
        if not skills:
            raise SystemExit(f"No SKILL.md found under {skills_dir}")
        register_skill_tool(registry, skills)
        index = skill_index(skills)
        print(f"Skills catalogue ({len(skills)} skill, {len(index)} chars in the system prompt):")
        print(index)

    agent = ToolAgent(
        client,
        registry,
        verifier=make_verifier(require_skill=use_skills),
        skill_index=index,
        model=model,
        max_steps=max_steps,
    )
    result = agent.run(TASK_PROMPT)

    for step in result.steps:
        print(f"\n--- Step {step.index} ---")
        print(step.model_text.strip())
        if step.observation is not None:
            preview = step.observation if len(step.observation) <= 300 else step.observation[:300] + " ..."
            print(f"Observation: {preview}")

    print(f"\nStopped: {result.stopped_reason}")
    print(f"Answer: {json.dumps(result.answer, ensure_ascii=False)}")

    grade = grade_run(result.answer, registry, resolve_fn, require_skill=use_skills)
    print_grade(label, grade)
    return {
        "answer": result.answer,
        "stopped_reason": result.stopped_reason,
        "turns": len(result.steps),
        "tool_calls": registry.history,
        "grade": asdict(grade),
    }


def run_sandbox_check(implementation: str) -> dict:
    _, resolve_fn = load_implementation(implementation)
    print("\n=== SANDBOX RED TEAM ===")
    with tempfile.TemporaryDirectory() as tmp:
        root = build_attack_workspace(Path(tmp))
        attacks = run_attacks(resolve_fn, root)
        legitimate = run_legitimate(resolve_fn, root)
    for row in attacks:
        mark = "blocked" if row["blocked"] else "ESCAPED"
        print(f"  [{mark:>7}] {row['attack']:<18} {row['detail']}")
    print("  --- these must still be allowed ---")
    for row in legitimate:
        mark = "allowed" if row["allowed"] else "REFUSED"
        print(f"  [{mark:>7}] {row['case']:<18} {row['detail']}")
    grade = grade_sandbox(resolve_fn)
    print_grade("SANDBOX", grade)
    return {"attacks": attacks, "legitimate": legitimate, "grade": asdict(grade)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("noskill", "skill", "compare", "sandbox"),
        default="compare",
        help="Run the bare agent, the skill-equipped agent, both, or only the red team.",
    )
    parser.add_argument("--offline", action="store_true", help="Use the scripted mock, no API calls.")
    parser.add_argument("--model", default=os.getenv("ZAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument(
        "--implementation",
        choices=("solution", "starter"),
        default="solution",
        help="Use the reference tools or the student TODO file.",
    )
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR)
    parser.add_argument("--trace-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.max_steps <= 40:
        raise SystemExit("--max-steps must be between 1 and 40")

    run_data: dict = {"mode": args.mode, "offline": args.offline, "implementation": args.implementation}

    if args.mode == "sandbox":
        run_data["sandbox"] = run_sandbox_check(args.implementation)
    else:
        shutil.rmtree(WORKSPACE_ROOT / "reports", ignore_errors=True)
        modes = []
        if args.mode in ("noskill", "compare"):
            modes.append(("NO SKILL: tools only", False))
        if args.mode in ("skill", "compare"):
            modes.append(("SKILL: procedure loaded on demand", True))

        for label, use_skills in modes:
            client = ScriptedMockClient() if args.offline else ZhipuClient.from_env()
            run_data["skill" if use_skills else "noskill"] = run_mode(
                client,
                label=label,
                use_skills=use_skills,
                model=args.model,
                max_steps=args.max_steps,
                implementation=args.implementation,
                skills_dir=args.skills_dir,
                workspace=WORKSPACE_ROOT,
            )

    if args.trace_out:
        args.trace_out.parent.mkdir(parents=True, exist_ok=True)
        args.trace_out.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nTrace saved to: {args.trace_out}")


if __name__ == "__main__":
    main()
