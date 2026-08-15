"""Grading for both halves of the lesson.

PART A (the demo) is graded PASS/FAIL - four checks, all must hold. The demo
exists to show one contrast, not to award points.

PART B (the pipeline) is graded on chapter 2's 20-point scale, split by TODO:
extraction 4, write gate 6 (all or nothing - this chapter's sandbox item),
reconcile 6, context ladder 4. Anything short of full marks fails.

One boundary carried over from chapter 2: ``finish_verifier`` never checks
answer VALUES - its errors are fed back to the model as Observations, and a
verifier that compares against the expected answer quietly hands the model
the answer. It checks shape and process only, against the agent's own tool
history. ``grade_*`` may check values; grading is supposed to know the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sessions import (
    EXPECTED_ANSWER,
    EXPECTED_EXTRACTED,
    EXPECTED_PIPELINE_MEMORY,
    FORBIDDEN_IN_MEMORY,
    REQUIRED_CALCULATOR_RESULTS,
    REQUIRED_READS,
    TRANSCRIPT,
)

# The last thing the user actually said - TODO 4 must keep it verbatim.
FINAL_INSTRUCTION = [m for m in TRANSCRIPT if m["role"] == "user"][-1]["content"]

DEMO_CHECKS = 4          # Part A: all four or FAIL
PIPELINE_TOTAL = 20      # Part B: TODO1 4 + TODO2 6 + TODO3 6 + TODO4 4


@dataclass
class Grade:
    passed: bool
    score: int
    total: int
    feedback: list[str] = field(default_factory=list)


def _normalise(value: object) -> str:
    return " ".join(str(value).strip().lower().split())


def _calculator_outputs(registry) -> set[str]:
    return {
        event["output"]
        for event in registry.history
        if event["tool"] == "calculate" and event["ok"]
    }


def _files_read(registry) -> set[str]:
    return {
        str(event["arguments"].get("path", "")).lstrip("./")
        for event in registry.history
        if event["tool"] == "read_file" and event["ok"]
    }


# ---------------------------------------------------------------------------
# PART A - the demo
# ---------------------------------------------------------------------------


def finish_verifier(answer: dict | None, registry) -> list[str]:
    """Gate on finish. Errors go back to the model as an Observation.

    Shape and process only - never the expected answer. The agent may not
    declare success until its own tool history shows it did the work.
    """
    errors: list[str] = []
    if not isinstance(answer, dict):
        return ["provide a JSON object with the two requested fields"]

    placeholders = [
        fname
        for fname in EXPECTED_ANSWER
        if str(answer.get(fname, "")).strip() in ("", "...", "<missing>", "unknown")
    ]
    if placeholders:
        errors.append(f"the JSON is missing real values for {placeholders}")

    total = _normalise(answer.get("total_fine"))
    if total and not total.isdigit():
        errors.append("total_fine must be a plain number")

    if not registry.called("calculate"):
        errors.append("compute the total with the calculate tool instead of asserting it")
    elif total and total.isdigit() and total not in _calculator_outputs(registry):
        # Not an answer check: whatever number is submitted must be one the
        # calculator actually returned, judged against the agent's OWN history.
        errors.append(
            "total_fine must be the exact Observation of a calculate call - "
            "compute record count times the per-record fine"
        )
    if not any(path.startswith("incident_") for path in _files_read(registry)):
        errors.append("read the incident file in the workspace before answering")
    return errors


def grade_demo(answer: dict | None, registry) -> Grade:
    """PASS/FAIL: both fields right, the total computed, the right file read."""
    feedback: list[str] = []
    score = 0

    if isinstance(answer, dict) and _normalise(answer.get("records")) == _normalise(
        EXPECTED_ANSWER["records"]
    ):
        score += 1
    else:
        got = answer.get("records", "<missing>") if isinstance(answer, dict) else None
        feedback.append(f"records: expected {EXPECTED_ANSWER['records']!r}, got {got!r}")

    if isinstance(answer, dict) and _normalise(answer.get("total_fine")) == _normalise(
        EXPECTED_ANSWER["total_fine"]
    ):
        score += 1
    else:
        got = answer.get("total_fine", "<missing>") if isinstance(answer, dict) else None
        feedback.append(f"total_fine: expected {EXPECTED_ANSWER['total_fine']!r}, got {got!r}")

    if REQUIRED_CALCULATOR_RESULTS <= _calculator_outputs(registry):
        score += 1
    else:
        feedback.append("the calculator never returned the total - it was asserted, not computed")

    if REQUIRED_READS <= _files_read(registry):
        score += 1
    else:
        feedback.append(
            f"the incident file ({sorted(REQUIRED_READS)}) was never read with read_file"
        )

    return Grade(score == DEMO_CHECKS, score, DEMO_CHECKS,
                 feedback or ["Answer, arithmetic and file read all check out."])


# ---------------------------------------------------------------------------
# PART B - the pipeline
# ---------------------------------------------------------------------------


def grade_pipeline(store, candidates: list, assembled, budget: int) -> Grade:
    """The 20-point report card, one block per TODO."""
    feedback: list[str] = []
    score = 0

    # ---- TODO 1 - extraction: 4 x 1 ------------------------------------
    # Matched by key OR by value: a live model names keys with its own taste
    # (audit_file for log_file), and failing a run over that would grade the
    # model's naming, not the student's extraction.
    def _extracted(key: str, value: str) -> bool:
        for c in candidates:
            if not isinstance(c, dict):
                continue
            if str(c.get("key", "")) == key:
                return True
            if _normalise(value) in _normalise(c.get("value", "")):
                return True
        return False

    for key, value in EXPECTED_EXTRACTED.items():
        if _extracted(key, value):
            score += 1
        else:
            feedback.append(f"TODO 1: expected fact {key!r} was never extracted")

    # ---- TODO 2 - the write gate: 6, all or nothing ---------------------
    # The gate is judged against what it was actually OFFERED. A live model
    # sometimes extracts cleanly, and an idle gate on a clean run is not a
    # failure - the notebook's attack-set cell is where the gate is always
    # exercised. A leak is a failure, always.
    def _rejectable(c) -> bool:
        if not isinstance(c, dict):
            return True
        blob = f'{c.get("key", "")} {c.get("value", "")}'
        if any(fragment in blob for fragment in FORBIDDEN_IN_MEMORY):
            return True
        value = c.get("value")
        if not isinstance(value, str) or not any(ch.isalnum() for ch in value):
            return True
        return " and " in value

    leaked = store.leaked_secrets(FORBIDDEN_IN_MEMORY)
    offered_bad = [c for c in candidates if _rejectable(c)]
    if leaked:
        feedback.append(
            f"TODO 2: a credential reached the store (matched {leaked}) - "
            "one leak and the whole gate item is 0"
        )
    elif offered_bad and not store.rejections:
        feedback.append(
            "TODO 2: the gate never rejected anything, but extraction offered "
            f"{len(offered_bad)} candidate(s) it should have caught - the gate "
            "is not running"
        )
    else:
        score += 6

    # ---- TODO 3 - reconcile: 2 + 2 + 1 + 1 ------------------------------
    # Value matching is loose ("250 yuan" counts as 250) for the same reason
    # extraction matching is: the operation is the student's work, the exact
    # string is the model's.
    current_fine = store.get("fine_per_violation")
    superseded = [
        r for r in store.all("superseded")
        if r["key"] == "fine_per_violation" and "200" in _normalise(r["value"])
    ]
    if (current_fine is not None
            and "250" in _normalise(current_fine["value"]) and superseded):
        score += 2
    else:
        feedback.append(
            "TODO 3: fine_per_violation must be 250 (current) with the old 200 "
            "marked superseded - UPDATE keeps the audit trail"
        )

    def _about(record: dict, subject: str) -> bool:
        return subject in _normalise(record.get("key", "")) or _normalise(
            record.get("value", "")
        ) == subject

    subject = EXPECTED_PIPELINE_MEMORY["revoked_subjects"][0]
    deleted_ok = any(_about(r, subject) for r in store.all("deleted"))
    still_current = any(_about(r, subject) for r in store.all("current"))
    if deleted_ok and not still_current:
        score += 2
    else:
        feedback.append(
            f"TODO 3: the {subject!r} fact should be marked deleted - the "
            "revocation pass did not apply (or deleted the wrong thing)"
        )

    verdicts = {op["op"] for op in store.operations}
    if "NOOP" in verdicts:
        score += 1
    else:
        feedback.append(
            "TODO 3: NOOP never occurred - the repeated incident_file fact "
            "should be judged already-known, not re-written (and not screened "
            "out by TODO 2, which must not compare against state)"
        )
    if "ADD" in verdicts:
        score += 1
    else:
        feedback.append("TODO 3: ADD never occurred - the new facts were not written")

    # ---- TODO 4 - the ladder: 2 + 1 + 1 ---------------------------------
    if assembled is not None and assembled.tokens <= budget:
        score += 2
    else:
        got = "nothing" if assembled is None else f"{assembled.tokens:,}t"
        feedback.append(f"TODO 4: assembled context must fit {budget:,}t (got {got})")

    ladder = list(assembled.ladder) if assembled is not None else []
    trim_at = next((i for i, line in enumerate(ladder) if "trim" in line.lower()), None)
    compact_at = next((i for i, line in enumerate(ladder) if "compact" in line.lower()), None)
    if trim_at is not None and (compact_at is None or trim_at < compact_at):
        score += 1
    else:
        feedback.append(
            "TODO 4: L1 (trim) must be attempted before L2 (compact) - cheap "
            "and lossless before expensive and lossy"
        )
    kept_verbatim = assembled is not None and any(
        FINAL_INSTRUCTION in str(m.get("content", "")) for m in assembled.messages
    )
    if kept_verbatim:
        score += 1
    else:
        feedback.append(
            "TODO 4: the user's final instruction must survive verbatim - a "
            "summarised instruction has lost the wording needed to follow it"
        )

    return Grade(score == PIPELINE_TOTAL, score, PIPELINE_TOTAL,
                 feedback or ["Extraction, gate, reconcile and ladder all correct."])
