#!/usr/bin/env python3
"""PART A - why an agent needs memory. Two runs of the same two sessions.

    tools    chapter 2's agent, unchanged: same sandboxed tools, fresh context
             every session, nothing kept. Session 1 told it which incident
             file matters and what the fine is; by session 2 that knowledge is
             gone, and no tool can read what was never written to disk. FAILS.
    memory   the same tools plus a memory pipeline: when a session ends, the
             durable facts are extracted, gated and stored; session 2 starts
             with a [memory] block. PASSES.

Every run calls the real Zhipu API: export ZAI_API_KEY (or ZHIPU_API_KEY)
first.

    python agent/main.py --mode compare            # both runs, one verdict table
    python agent/main.py --mode tools              # watch chapter 2's agent fail
    python agent/main.py --mode memory
    python agent/main.py --mode memory --session 1 # build the store, then look at it
    python agent/main.py --mode memory --session 2 # answer from the store on disk

Part B (the four TODOs) lives in pipeline.py and the notebook, not here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap  # noqa: E402,F401  (puts the lesson folders on sys.path)

from grader import finish_verifier, grade_demo
from memory_agent import ToolsPolicy
from memory_store import MemoryStore
from react_loop import DEFAULT_MAX_STEPS, run_sessions
from sessions import (
    AGENT_SYSTEM_TEMPLATE,
    EXPECTED_ANSWER,
    SESSIONS,
    STUDENT_ROOT,
    WORKSPACE_ROOT,
    reset_workspace,
)
from tokens import estimator_name
from tools import build_agent_registry
from trace_display import run_banner, summary_card
from zhipu_client import DEFAULT_MODEL, ZhipuClient

RUNS_ROOT = STUDENT_ROOT / "runs"


def make_client():
    return ZhipuClient.from_env()


def make_memory_policy(implementation: str, model: str):
    if implementation == "starter":
        # The class the notebook binds your methods onto - "starter" only
        # works once the notebook's TODO cells have run in the same kernel.
        from memory_policy import MemoryPolicy as StarterPolicy

        return StarterPolicy(model=model)
    from memory_agent import MemoryPolicy

    return MemoryPolicy(model=model)


def run_one(mode: str, args, client) -> dict:
    label = mode
    run_banner(label, 0)

    # Only the memory run keeps a store file; the tools run holds an empty
    # in-memory store - that is its point.
    if mode == "memory":
        store = MemoryStore.load(RUNS_ROOT, "memory.jsonl")
        policy = make_memory_policy(args.implementation, args.model)
    else:
        store = MemoryStore()
        policy = ToolsPolicy()
    if args.session is None:
        store.reset()

    registry = build_agent_registry(WORKSPACE_ROOT)
    system_prompt = AGENT_SYSTEM_TEMPLATE.format(tools=registry.describe())

    try:
        result = run_sessions(
            client=client,
            policy=policy,
            store=store,
            sessions=SESSIONS,
            system_prompt=system_prompt,
            registry=registry,
            verifier=finish_verifier,
            model=args.model,
            only_session=args.session,
            verbose=not args.quiet,
            max_steps=args.max_steps,
            answer_keys=set(EXPECTED_ANSWER),
            on_session_start=lambda _n: reset_workspace(),
        )
    except NotImplementedError as exc:
        print(f"\nStarter is incomplete: {exc}")
        return {"mode": mode, "error": str(exc)}

    grade = grade_demo(result.answer, registry)
    peak = max((t.context_tokens for t in result.turns), default=0)
    api = getattr(client, "log", None)

    partial = args.session == 1  # the deliverable is asked for in session 2
    summary_card(
        label=label, budget=0,
        passed=grade.passed, score=grade.score, total=grade.total,
        feedback=grade.feedback,
        answer=result.answer, stopped=result.stopped_reason, peak=peak,
        compactions=0, rung=0,
        mem=(len(store.all("current")), len(store.all("superseded")),
             len(store.all("deleted"))),
        api=api.summary() if api is not None else "",
        drift=result.drift.summary(),
        partial_note=("session 1 only — the deliverable is requested in "
                      "session 2; look at runs/memory.jsonl instead"
                      if partial else None),
    )

    return {
        "mode": mode,
        "passed": grade.passed,
        "score": grade.score,
        "total": grade.total,
        "answer": result.answer,
        "stopped_reason": result.stopped_reason,
        "grade": asdict(grade),
        "peak_context_tokens": peak,
        "api_calls": api.total_calls if api else 0,
        "api_prompt_tokens": api.total_prompt_tokens if api else 0,
        "turns": [asdict(t) for t in result.turns],
        "tool_calls": registry.history,
        "memory": store.all("*"),
        "rejections": store.rejections,
    }


def print_comparison(runs: list[dict]) -> None:
    print(f"\n{'=' * 72}\nCOMPARISON   (estimator {estimator_name()})\n{'=' * 72}")
    header = f"{'run':<10}{'result':>10}{'answer':>34}{'api calls':>12}"
    print(header)
    print("-" * len(header))
    for data in runs:
        if "error" in data:
            print(f"{data['mode']:<10}{'ERROR':>10}")
            continue
        shown = json.dumps(data["answer"], ensure_ascii=False)
        if len(shown) > 32:
            shown = shown[:29] + "..."
        print(
            f"{data['mode']:<10}"
            f"{'PASS' if data['passed'] else 'FAIL':>10}"
            f"{shown:>34}"
            f"{data['api_calls']:>12}"
        )

    by_mode = {d["mode"]: d for d in runs if "error" not in d}
    tools, memory = by_mode.get("tools"), by_mode.get("memory")
    if tools and memory:
        print(
            "\nSame tools, same loop, same model, same grader. The only line of "
            "code that differs is what happens when a session ends: the tools "
            "run keeps nothing, the memory run extracts two facts (~20 tokens) "
            "and session 2 starts with them in a [memory] block. Tools extend "
            "what an agent can DO; memory extends what it can KEEP."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("tools", "memory", "compare"),
                        default="compare")
    parser.add_argument("--model", default=os.getenv("ZAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--implementation", choices=("solution", "starter"),
                        default="solution",
                        help="Which memory pipeline the memory run uses.")
    parser.add_argument("--session", type=int, choices=(1, 2), default=None,
                        help="Run one session against the memory file already on disk.")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                        help=f"Steps allowed per user turn (default {DEFAULT_MAX_STEPS}).")
    parser.add_argument("--trace-out", type=Path)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.max_steps <= 20:
        raise SystemExit("--max-steps must be between 1 and 20")
    if args.session is not None and args.mode != "memory":
        raise SystemExit("--session only makes sense with --mode memory "
                         "(the tools run keeps nothing between sessions)")

    runs: list[dict] = []
    # A fresh client per run so the API accounting is per-run, not cumulative.
    if args.mode in ("tools", "compare"):
        runs.append(run_one("tools", args, make_client()))
    if args.mode in ("memory", "compare"):
        runs.append(run_one("memory", args, make_client()))

    if args.mode == "compare":
        print_comparison(runs)

    if args.trace_out:
        args.trace_out.parent.mkdir(parents=True, exist_ok=True)
        args.trace_out.write_text(
            json.dumps(
                {"model": args.model, "estimator": estimator_name(), "runs": runs},
                ensure_ascii=False, indent=2, default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nTrace saved to: {args.trace_out}")


if __name__ == "__main__":
    main()
