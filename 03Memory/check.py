#!/usr/bin/env python3
"""A readable test report for the lesson. Zero cost - runs on the mock.

    python check.py        # the two-section report below
    python check.py -v     # same report, plus full tracebacks at the end

It wraps standard unittest discovery (python -m unittest discover -s tests
still works and runs exactly the same tests) and renders the result in two
sections: YOUR TASK LIST (the four TODOs - red means "not done yet", not
"something broke") and GUARDRAILS (the harness proving itself healthy - these
should always be green).
"""

from __future__ import annotations

import argparse
import sys
import time
import unittest

from trace_display import BOLD, DIM, GREEN, RED, RESET, YELLOW, WIDTH

# The four checklist tests, in TODO order.
TODO_TESTS = [
    ("test_todo_1_write_memory_extracts_records", "TODO 1", "write_memory"),
    ("test_todo_2_validate_record_is_a_deterministic_gate", "TODO 2", "validate_record"),
    ("test_todo_3_reconcile_applies_all_four_verdicts", "TODO 3", "reconcile"),
    ("test_todo_4_build_context_fits_the_budget", "TODO 4", "build_context"),
]
CHECKLIST_MODULE = "test_starter_checklist"

# Guardrail modules, in display order.
GUARDRAILS = [
    ("test_write_gate", "write gate"),
    ("test_context_ladder", "context ladder"),
    ("test_demo", "Part A demo"),
    ("test_grader", "graders"),
    ("test_memory_store", "memory store"),
    ("test_pipeline", "reference pipeline"),
]


class Record:
    __slots__ = ("module", "name", "status", "reason", "trace")

    def __init__(self, module, name, status, reason="", trace=""):
        self.module, self.name = module, name
        self.status, self.reason, self.trace = status, reason, trace


class QuietResult(unittest.TestResult):
    """Collects one Record per test instead of printing tracebacks."""

    def __init__(self):
        super().__init__()
        self.records: list[Record] = []

    def _add(self, test, status, err=None):
        parts = test.id().split(".")
        module, name = parts[0], parts[-1]
        reason, trace = "", ""
        if err is not None:
            trace = self._exc_info_to_string(err, test)
            last = [l for l in trace.strip().splitlines() if l.strip()][-1]
            reason = last.split(":", 1)[-1].strip() if ":" in last else last
        self.records.append(Record(module, name, status, reason, trace))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, "fail", err)

    def addError(self, test, err):
        super().addError(test, err)
        self._add(test, "error", err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._add(test, "skip")

    def addSubTest(self, test, subtest, err):
        """subTest failures bypass addFailure - without this override they
        would vanish from the report entirely (and so would the parent test,
        which never calls addSuccess once a subTest has failed)."""
        super().addSubTest(test, subtest, err)
        if err is None:
            return  # successful subTests are covered by the parent's addSuccess
        parts = test.id().split(".")
        module, name = parts[0], parts[-1]
        trace = self._exc_info_to_string(err, test)
        last = [l for l in trace.strip().splitlines() if l.strip()][-1]
        reason = last.split(":", 1)[-1].strip() if ":" in last else last
        # Keep the subTest params so the report names the exact failing case,
        # e.g. test_rejects_other_credential_shapes (value='ghp_...').
        params = str(subtest).split(name, 1)[-1].strip()
        self.records.append(Record(module, f"{name} {params}".strip(),
                                   "fail", reason, trace))


def _clip(text: str, limit: int = 58) -> str:
    text = " ".join(str(text).split())
    return text[:limit] + "..." if len(text) > limit else text


def render(result: QuietResult, elapsed: float, verbose: bool) -> int:
    bar = "═" * WIDTH
    thin = "─" * WIDTH
    total = len(result.records)
    print(f"\n{BOLD}{bar}\n 03Memory · test report"
          f"{'':>{max(1, WIDTH - 40)}}{total} tests · {elapsed:.2f}s\n{bar}{RESET}")

    by_id = {(r.module, r.name): r for r in result.records}

    # ---- section 1: the four TODOs -------------------------------------
    print(f"\n {BOLD}YOUR TASK LIST{RESET}{DIM}  (red = not done yet, not a bug){RESET}")
    todo_done: list[bool] = []
    for test_name, todo, method in TODO_TESTS:
        record = by_id.get((CHECKLIST_MODULE, test_name))
        if record is None:
            print(f"   {YELLOW}? {todo}  {method:<18}test not found{RESET}")
            todo_done.append(False)
        elif record.status == "pass":
            print(f"   {GREEN}✓ {todo}  {method:<18}done{RESET}")
            todo_done.append(True)
        else:
            note = ("not started" if "not implemented yet" in record.reason
                    else _clip(record.reason))
            print(f"   {RED}✗ {todo}  {method:<18}{note}{RESET}")
            todo_done.append(False)

    # ---- section 2: the guardrails --------------------------------------
    print(f"\n {BOLD}GUARDRAILS{RESET}{DIM}  (green here means the harness itself is healthy){RESET}")
    guardrail_broken = False
    for module, label in GUARDRAILS:
        rows = [r for r in result.records if r.module == module
                and not (module == CHECKLIST_MODULE)]
        passed = sum(1 for r in rows if r.status == "pass")
        skipped = sum(1 for r in rows if r.status == "skip")
        bad = [r for r in rows if r.status in ("fail", "error")]
        ran = len(rows) - skipped
        note = ""
        if skipped:
            note = f"   {YELLOW}(+{skipped} ⏭ unlock when TODO 4 exists){RESET}"
        if bad:
            guardrail_broken = True
            print(f"   {RED}✗ {label:<19}{passed}/{ran}{RESET}{note}")
            for r in bad:
                print(f"       {RED}· {r.name}: {_clip(r.reason)}{RESET}")
        else:
            print(f"   {GREEN}✓ {label:<19}{passed}/{ran}{RESET}{note}")

    # unknown modules (e.g. import errors) - never hide them
    known = {m for m, _ in GUARDRAILS} | {CHECKLIST_MODULE}
    for r in result.records:
        if r.module not in known and r.status in ("fail", "error"):
            guardrail_broken = True
            print(f"   {RED}✗ {r.module}.{r.name}: {_clip(r.reason)}{RESET}")

    # ---- the bottom line -------------------------------------------------
    fails = sum(1 for r in result.records if r.status in ("fail", "error"))
    passes = sum(1 for r in result.records if r.status == "pass")
    skips = sum(1 for r in result.records if r.status == "skip")
    print(f"\n{thin}")
    undone = [TODO_TESTS[i][1] for i, ok in enumerate(todo_done) if not ok]
    if guardrail_broken:
        hint = f"{RED}a guardrail is red - the harness broke; check your last edit{RESET}"
    elif undone:
        hint = f"next: {BOLD}{undone[0]}{RESET}"
    else:
        hint = f"{GREEN}{BOLD}all four TODOs green{RESET} - next: python pipeline.py --implementation starter"
    print(f" {RED}✗ {fails} to do{RESET} · {GREEN}✓ {passes} passing{RESET} · "
          f"{YELLOW}⏭ {skips} waiting{RESET}        {hint}")

    if verbose:
        bad = [r for r in result.records if r.trace]
        if bad:
            print(f"\n{BOLD}FULL TRACEBACKS (-v){RESET}")
            for r in bad:
                print(f"\n{thin}\n{r.module}.{r.name}\n{thin}\n{r.trace}")

    return 1 if fails else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="also print full tracebacks after the report")
    args = parser.parse_args()

    suite = unittest.TestLoader().discover("tests")
    result = QuietResult()
    started = time.perf_counter()
    suite.run(result)
    elapsed = time.perf_counter() - started

    sys.exit(render(result, elapsed, args.verbose))


if __name__ == "__main__":
    main()
