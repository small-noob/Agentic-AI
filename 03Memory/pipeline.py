#!/usr/bin/env python3
"""PART B - drive the four TODOs over one long briefing transcript.

No agent, no ReAct loop, no question answering. Two inputs:

    the seed store    what "last month" left behind (three records)
    the transcript    one long handover conversation (sessions.TRANSCRIPT)

Each step is one TODO, and each step leaves its output in runs/ so the stages
can be compared afterwards - what extraction produced, what the gate removed,
what reconcile did to the store:

    runs/0_initial_memory.jsonl    the seed store, before anything runs
    runs/1_todo1_candidates.json   STEP 1  write_memory      (TODO 1)
    runs/2_todo2_gate.json         STEP 2  validate_record   (TODO 2)
    runs/3_todo3_operations.json   STEP 3  reconcile         (TODO 3)
    runs/final_memory.jsonl        the store after reconcile
    (STEP 4 build_context prints its ladder; the 20-point card ends the run)

Run everything at once, or one TODO at a time - later steps read the earlier
steps' files, so the chain survives across separate invocations:

    python3 pipeline.py --implementation starter             # all four steps
    python3 pipeline.py --implementation starter --step 1    # seed + TODO 1
    python3 pipeline.py --implementation starter --step 2    # TODO 2 (no API)
    python3 pipeline.py --implementation starter --step 3    # TODO 3
    python3 pipeline.py --implementation starter --step 4    # TODO 4 + report card

Every run calls the real API except step 2 (the gate never calls the model);
export ZAI_API_KEY first. The deterministic mock is exercised by the test
suite instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from grader import grade_pipeline
from memory_store import MemoryStore
from react_loop import ContextOverflow
from sessions import (
    EXPECTED_EXTRACTED,
    FORBIDDEN_IN_MEMORY,
    LESSON_ROOT,
    PIPELINE_BUDGET,
    PIPELINE_SYSTEM,
    SEED_MEMORY,
    TRANSCRIPT,
    TRANSCRIPT_SESSION_NO,
)
from tokens import estimator_name
from trace_display import BOLD, DIM, GREEN, RED, RESET, run_banner, verdict
from zhipu_client import DEFAULT_MODEL, ZhipuClient

RUNS_ROOT = LESSON_ROOT / "runs"

INITIAL_FILE = "0_initial_memory.jsonl"
FINAL_FILE = "final_memory.jsonl"
STEP_FILES = {
    1: "1_todo1_candidates.json",
    2: "2_todo2_gate.json",
    3: "3_todo3_operations.json",
}
LINEAGE = [INITIAL_FILE, *STEP_FILES.values(), FINAL_FILE]


# ---------------------------------------------------------------- plumbing

def make_policy(implementation: str, model: str):
    if implementation == "starter":
        from memory_starter import MemoryPolicy as StarterPolicy

        return StarterPolicy(model=model)
    from memory_agent import MemoryPolicy

    return MemoryPolicy(model=model)


def _banner(step: str, title: str) -> None:
    print(f"\n{BOLD}── {step} · {title} {'─' * max(0, 46 - len(title))}{RESET}")


def _save(name: str, payload) -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{DIM}  saved -> runs/{name}{RESET}")


def _require(name: str, produced_by: str):
    target = RUNS_ROOT / name
    if not target.exists():
        sys.exit(f"runs/{name} not found - run {produced_by} first.")
    return json.loads(target.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- feedback
# Instant per-step verdicts, printed the moment a step finishes. These are
# hints that mirror the grader; the authoritative score is STEP 4's card.

def _fb(ok, text: str) -> None:
    if ok is True:
        print(f"  {GREEN}✓ {text}{RESET}")
    elif ok is False:
        print(f"  {RED}✗ {text}{RESET}")
    else:
        print(f"  {DIM}· {text}{RESET}")


def _norm(value) -> str:
    return " ".join(str(value).strip().lower().split())


def _feedback1(candidates: list) -> None:
    print(f"\n{BOLD}  feedback (TODO 1){RESET}")
    hit, missing = 0, []
    for key, value in EXPECTED_EXTRACTED.items():
        found = any(
            isinstance(c, dict)
            and (str(c.get("key", "")) == key or _norm(value) in _norm(c.get("value", "")))
            for c in candidates
        )
        hit += found
        if not found:
            missing.append(key)
    _fb(hit == len(EXPECTED_EXTRACTED),
        f"{hit}/{len(EXPECTED_EXTRACTED)} expected facts extracted"
        + (f" - missing: {', '.join(missing)}" if missing else ""))
    if any(isinstance(c, dict) and c.get("key") == "ten_record_total" for c in candidates):
        _fb(False, "the assistant's wrong arithmetic was extracted - "
                   "flatten USER turns only")
    _fb(None, f"{len(candidates)} candidate(s) total (extras are fine; "
              "the gate and reconcile deal with them)")


def _feedback2(accepted: list, rejected: list) -> None:
    print(f"\n{BOLD}  feedback (TODO 2){RESET}")
    leaked = [
        c for c in accepted
        if isinstance(c, dict)
        and any(f in f'{c.get("key", "")} {c.get("value", "")}' for f in FORBIDDEN_IN_MEMORY)
    ]
    if leaked:
        _fb(False, f"A SECRET PASSED THE GATE: {leaked[0].get('key')} - "
                   "one leak makes the whole 6-point item 0")
    else:
        _fb(True, "nothing secret slipped through")
    if rejected:
        reasons = ", ".join(sorted({r["reason"] for r in rejected}))
        _fb(True, f"rejected {len(rejected)} candidate(s): {reasons}")
    else:
        _fb(None, "nothing was rejected this run - fine if extraction was "
                  "clean; the mock channel (check.py) always offers bad candidates")


def _feedback3(store) -> None:
    print(f"\n{BOLD}  feedback (TODO 3){RESET}")
    fine = store.get("fine_per_violation")
    superseded = [r for r in store.all("superseded")
                  if r["key"] == "fine_per_violation" and "200" in _norm(r["value"])]
    _fb(bool(fine and "250" in _norm(fine["value"]) and superseded),
        "UPDATE kept the audit trail (fine 250 current, 200 superseded)")
    deleted = any("security-team" in _norm(r.get("value", "")) or
                  "security" in _norm(r.get("key", ""))
                  for r in store.all("deleted"))
    still = any("security-team" in _norm(r.get("value", ""))
                for r in store.all("current"))
    _fb(deleted and not still, "revocation applied (security-team deleted, "
                               "nothing current still mentions it)")
    seen = {op["op"] for op in store.operations}
    _fb({"ADD", "UPDATE", "DELETE", "NOOP"} <= seen,
        f"verdicts seen: {', '.join(sorted(seen)) or 'none'} "
        "(all four occur in this transcript)")
    _fb(None if not store.leaked_secrets(FORBIDDEN_IN_MEMORY) else False,
        "grep \"sk-\" runs/final_memory.jsonl must print nothing"
        if not store.leaked_secrets(FORBIDDEN_IN_MEMORY)
        else "A SECRET IS IN THE FINAL STORE")


def _render_ladder(assembled) -> None:
    """The rungs: red ✗ = did not fit, climb; green ✓ = landed."""
    print(f"  {DIM}the ladder - cheap before expensive, lossless before lossy:{RESET}")
    for line in assembled.ladder:
        text = " ".join(str(line).split())
        if text.endswith("OK"):
            print(f"    {GREEN}{BOLD}✓ {text}   <- landed here{RESET}")
        else:
            print(f"    {RED}✗ {text}   -> does not fit, climb{RESET}")


def _feedback4(assembled, budget: int) -> None:
    from grader import FINAL_INSTRUCTION

    print(f"\n{BOLD}  feedback (TODO 4){RESET}")
    _fb(assembled.tokens <= budget,
        f"fits the budget ({assembled.tokens:,}t <= {budget:,}t)")
    ladder = assembled.ladder
    trim_at = next((i for i, l in enumerate(ladder) if "trim" in l.lower()), None)
    compact_at = next((i for i, l in enumerate(ladder) if "compact" in l.lower()), None)
    _fb(trim_at is not None and (compact_at is None or trim_at < compact_at),
        "L1 (trim, free) was attempted before L2 (compact, one API call)")
    _fb(any(FINAL_INSTRUCTION in str(m.get("content", "")) for m in assembled.messages),
        "the user's final instruction survives verbatim in the tail")


# ---------------------------------------------------------------- the steps

def step1(policy, client) -> list:
    """Seed the initial store, then TODO 1: transcript -> candidates."""
    # A fresh lineage: stale files from an earlier run must not masquerade
    # as this run's output.
    for name in LINEAGE:
        (RUNS_ROOT / name).unlink(missing_ok=True)

    store = MemoryStore.load(RUNS_ROOT, INITIAL_FILE)
    for record in SEED_MEMORY:
        store.add(dict(record))
    store.operations.clear()  # seeding is scaffolding, not part of the run
    store.save()
    print(f"{DIM}seed store: " + " | ".join(
        f'{r["key"]}={r["value"]}' for r in store.all()) + RESET)
    print(f"{DIM}  saved -> runs/{INITIAL_FILE}{RESET}")

    _banner("STEP 1", "write_memory (extract)")
    candidates = policy.write_memory(client, TRANSCRIPT, TRANSCRIPT_SESSION_NO)
    for record in candidates:
        print(f"  · {json.dumps(record, ensure_ascii=False)}")
    if not candidates:
        print("  (no candidates extracted)")
    _save(STEP_FILES[1], candidates)
    _feedback1(candidates)
    return candidates


def step2(policy, candidates=None) -> tuple[list, list]:
    """TODO 2: candidates -> accepted + rejected. No API call, on purpose."""
    if candidates is None:
        candidates = _require(STEP_FILES[1], "--step 1")
    store = MemoryStore.load(RUNS_ROOT, INITIAL_FILE)  # reference only

    _banner("STEP 2", "validate_record (the write gate)")
    accepted, rejected = [], []
    for record in candidates:
        ok, reason = policy.validate_record(record, store)
        if ok:
            accepted.append(record)
            print(f"  {GREEN}✓ pass{RESET}   {json.dumps(record, ensure_ascii=False)}")
        else:
            rejected.append({"record": record, "reason": reason})
            print(f"  {RED}✗ reject{RESET} {json.dumps(record, ensure_ascii=False)}"
                  f"  {RED}({reason}){RESET}")
    _save(STEP_FILES[2], {"accepted": accepted, "rejected": rejected})
    _feedback2(accepted, rejected)
    return accepted, rejected


def step3(policy, client, accepted=None, rejected=None) -> MemoryStore:
    """TODO 3: accepted -> ADD/UPDATE/DELETE/NOOP against the seed store."""
    if accepted is None:
        gate = _require(STEP_FILES[2], "--step 2")
        accepted, rejected = gate["accepted"], gate["rejected"]

    initial = MemoryStore.load(RUNS_ROOT, INITIAL_FILE)
    if not initial.records:
        sys.exit(f"runs/{INITIAL_FILE} is empty - run --step 1 first.")
    store = MemoryStore(root=RUNS_ROOT, relpath=FINAL_FILE)
    store.records = [dict(r) for r in initial.records]
    store.rejections = list(rejected or [])

    _banner("STEP 3", "reconcile (ADD / UPDATE / DELETE / NOOP)")
    policy.reconcile(client, store, accepted, TRANSCRIPT, TRANSCRIPT_SESSION_NO)
    store.save()
    for op in store.operations:
        print(f"  · {json.dumps(op, ensure_ascii=False)}")
    print()
    print(store.report(TRANSCRIPT_SESSION_NO))
    _save(STEP_FILES[3], {"operations": store.operations,
                          "store_after": store.all("*")})
    print(f"{DIM}  saved -> runs/{FINAL_FILE}{RESET}")
    _feedback3(store)
    return store


def step4(policy, client, budget: int, store=None, candidates=None) -> None:
    """TODO 4: assemble under the budget, then the 20-point report card."""
    if candidates is None:
        candidates = _require(STEP_FILES[1], "--step 1")
    if store is None:
        store = MemoryStore.load(RUNS_ROOT, FINAL_FILE)
        if not store.records:
            sys.exit(f"runs/{FINAL_FILE} not found - run --step 3 first.")
        # Restore what grading needs from the earlier steps' files.
        gate = _require(STEP_FILES[2], "--step 2")
        store.rejections = list(gate["rejected"])
        ops = _require(STEP_FILES[3], "--step 3")
        store.operations = list(ops["operations"])

    _banner("STEP 4", f"build_context (budget {budget:,}t)")
    print(f"{DIM}  task: fit the whole transcript + the store into {budget:,}t "
          f"for the next model call (estimator {estimator_name()}){RESET}")
    history = [{"role": m["role"], "content": m["content"]} for m in TRANSCRIPT]
    assembled = None
    try:
        assembled = policy.build_context(client, PIPELINE_SYSTEM, store, history, budget)
        _render_ladder(assembled)
        _feedback4(assembled, budget)
    except ContextOverflow as exc:
        print(f"  {RED}{BOLD}CONTEXT OVERFLOW ▸ {exc}{RESET}")
        print(f"\n{BOLD}  feedback (TODO 4){RESET}")
        _fb(False, "nothing fits the budget - the ladder must degrade "
                   "step by step, not give up")

    grade = grade_pipeline(store, candidates, assembled, budget)
    print(f"\n{'─' * 72}")
    print(f" 🏆 pipeline   {verdict(grade.passed, grade.score, grade.total)}")
    print(f"{'─' * 72}")
    mark, colr = ("✓", GREEN) if grade.passed else ("✗", RED)
    for item in grade.feedback:
        print(f" {colr}{mark} {item}{RESET}")
    api = getattr(client, "log", None)
    if api is not None:
        print(f"\n{DIM} api: {api.summary()}{RESET}")
    print(f"{DIM} store: runs/{FINAL_FILE}  (grep \"sk-\" it - must print nothing){RESET}")


# ------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", choices=("solution", "starter"),
                        default="solution")
    parser.add_argument("--step", type=int, choices=(1, 2, 3, 4), default=None,
                        help="Run one TODO; later steps read the earlier "
                             "steps' files from runs/. Omit to run all four.")
    parser.add_argument("--model", default=os.getenv("ZAI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--budget", type=int, default=PIPELINE_BUDGET,
                        help=f"Token budget for STEP 4 (default {PIPELINE_BUDGET}).")
    args = parser.parse_args()

    client = ZhipuClient.from_env()
    policy = make_policy(args.implementation, args.model)
    label = f"pipeline ({args.implementation})" + (
        f" · step {args.step}" if args.step else "")
    run_banner(label, args.budget if args.step in (None, 4) else 0)

    try:
        if args.step is None:
            candidates = step1(policy, client)
            accepted, rejected = step2(policy, candidates)
            store = step3(policy, client, accepted, rejected)
            step4(policy, client, args.budget, store, candidates)
        elif args.step == 1:
            step1(policy, client)
            print(f"\n{DIM}next: python pipeline.py --implementation "
                  f"{args.implementation} --step 2{RESET}")
        elif args.step == 2:
            step2(policy)
            print(f"\n{DIM}next: python pipeline.py --implementation "
                  f"{args.implementation} --step 3{RESET}")
        elif args.step == 3:
            step3(policy, client)
            print(f"\n{DIM}next: python pipeline.py --implementation "
                  f"{args.implementation} --step 4{RESET}")
        else:
            step4(policy, client, args.budget)
    except NotImplementedError as exc:
        print(f"\nStarter is incomplete: {exc}")
        print("Finish that TODO, then run again - the steps run in order.")


if __name__ == "__main__":
    main()
