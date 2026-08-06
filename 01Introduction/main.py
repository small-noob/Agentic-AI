#!/usr/bin/env python3
"""CLI for comparing one-shot Direct inference with a tool-using ReAct loop."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from direct_agent import run_direct
from grader import extract_json_answer, grade_answer, grade_react_run
from mock_client import ScriptedMockClient
from react_agent import ReactAgent
from task import TASK_PROMPT
from tools import ToolEnvironment
from zhipu_client import DEFAULT_MODEL, ZhipuClient


def print_grade(label: str, grade, total: int) -> None:
    status = "PASS" if grade.passed else "FAIL"
    print(f"\n[{label}] {status} — {grade.score}/{total}")
    for item in grade.feedback:
        print(f"  - {item}")


def run_direct_mode(client, model: str):
    print("\n=== DIRECT: one model call, no tools ===")
    response = run_direct(client, TASK_PROMPT, model=model)
    print(response)
    grade = grade_answer(extract_json_answer(response))
    print_grade("DIRECT", grade, 10)
    return {"response": response, "grade": asdict(grade)}


def run_react_mode(client, model: str, max_steps: int, implementation: str):
    print("\n=== REACT: Thought → Action → Observation ===")
    tools = ToolEnvironment()
    if implementation == "starter":
        from react_starter import StarterReactAgent

        agent = StarterReactAgent(client, tools, model=model, max_steps=max_steps)
    else:
        agent = ReactAgent(client, tools, model=model, max_steps=max_steps)

    try:
        result = agent.run(TASK_PROMPT)
    except NotImplementedError as exc:
        print(f"Starter is incomplete: {exc}")
        return {"error": str(exc), "tool_history": tools.history}

    for step in result.steps:
        print(f"\n--- Step {step.index} ---")
        print(step.model_text)
        if step.observation is not None:
            print(f"Observation: {step.observation}")
    print(f"\nStopped: {result.stopped_reason}")
    print(f"Answer: {json.dumps(result.answer, ensure_ascii=False)}")

    grade = grade_react_run(result.answer, tools.history)
    print_grade("REACT", grade, 12)
    return {
        "answer": result.answer,
        "stopped_reason": result.stopped_reason,
        "steps": [asdict(step) for step in result.steps],
        "tool_history": tools.history,
        "grade": asdict(grade),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("direct", "react", "compare"),
        default="compare",
        help="Run one-shot Direct, ReAct, or both (default: compare).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use a deterministic no-cost mock instead of calling the Zhipu API.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("ZAI_MODEL", DEFAULT_MODEL),
        help=f"Zhipu model id (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument(
        "--implementation",
        choices=("solution", "starter"),
        default="solution",
        help="Use the complete reference loop or the student TODO file.",
    )
    parser.add_argument(
        "--trace-out",
        type=Path,
        help="Optionally save responses, actions, observations, and grades as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_steps < 1 or args.max_steps > 30:
        raise SystemExit("--max-steps must be between 1 and 30")

    client = ScriptedMockClient() if args.offline else ZhipuClient.from_env()
    run_data = {
        "mode": args.mode,
        "offline": args.offline,
        "model": args.model,
    }

    if args.mode in ("direct", "compare"):
        run_data["direct"] = run_direct_mode(client, args.model)
    if args.mode in ("react", "compare"):
        run_data["react"] = run_react_mode(
            client,
            args.model,
            args.max_steps,
            args.implementation,
        )

    if args.trace_out:
        args.trace_out.parent.mkdir(parents=True, exist_ok=True)
        args.trace_out.write_text(
            json.dumps(run_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nTrace saved to: {args.trace_out}")


if __name__ == "__main__":
    main()
