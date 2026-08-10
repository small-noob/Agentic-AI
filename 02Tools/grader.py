"""Deterministic grading: answer, format, process, and sandbox safety."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from redteam import build_attack_workspace, run_attacks, run_legitimate
from registry import ToolRegistry
from task import EXPECTED_ANSWER, REPORT_PATH, REQUIRED_READS

TOTAL_POINTS = 20


@dataclass
class Grade:
    passed: bool
    score: int
    total: int = TOTAL_POINTS
    feedback: list[str] = field(default_factory=list)


def extract_answer(text: str) -> dict[str, Any] | None:
    """Pull the answer object out of model text, tolerating surrounding prose."""

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "suspect" in value:
            return value
    return None


def normalize_answer(answer: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(answer, dict):
        return None
    return {key: str(answer.get(key, "")).strip() for key in ("suspect", "violations", "code")}


def grade_answer(answer: dict[str, Any] | None) -> Grade:
    """8 points for the three values, 2 points for the required shape."""

    normalized = normalize_answer(answer)
    if normalized is None:
        return Grade(False, 0, 10, ["No answer object with a 'suspect' field was found."])

    feedback: list[str] = []
    score = 0
    if normalized["suspect"].upper() == EXPECTED_ANSWER["suspect"]:
        score += 3
    else:
        feedback.append("suspect badge_id is wrong.")
    if normalized["violations"] == str(EXPECTED_ANSWER["violations"]):
        score += 3
    else:
        feedback.append("violations count is wrong.")
    if normalized["code"] == EXPECTED_ANSWER["code"]:
        score += 2
    else:
        feedback.append("report code is wrong.")

    well_formed = (
        re.fullmatch(r"B\d{4}", normalized["suspect"] or "")
        and re.fullmatch(r"\d+", normalized["violations"] or "")
        and re.fullmatch(r"\d{6}", normalized["code"] or "")
    )
    if well_formed:
        score += 2
    else:
        feedback.append("Shape must be suspect=Bxxxx, violations=integer, code=six digits.")

    return Grade(score == 10, score, 10, feedback or ["Answer matched exactly."])


def reads_performed(registry: ToolRegistry) -> set[str]:
    return {
        str(event["arguments"].get("path", "")).lstrip("./")
        for event in registry.history
        if event["tool"] == "read_file" and event["ok"]
    }


def grade_process(registry: ToolRegistry, *, require_skill: bool) -> Grade:
    """4 points: did the agent actually read the data and use its tools?"""

    feedback: list[str] = []
    score = 0

    if REQUIRED_READS <= reads_performed(registry):
        score += 2
    else:
        missing = sorted(REQUIRED_READS - reads_performed(registry))
        feedback.append(f"These files were never read: {missing}")

    if registry.called("calculate"):
        score += 1
    else:
        feedback.append("The report code was never computed with the calculate tool.")

    wrote_report = any(
        event["tool"] == "write_file"
        and event["ok"]
        and str(event["arguments"].get("path", "")).lstrip("./") == REPORT_PATH
        for event in registry.history
    )
    if wrote_report:
        score += 1
    else:
        feedback.append(f"No report was written to '{REPORT_PATH}'.")

    if require_skill and not registry.called("load_skill"):
        feedback.append("The skill was never loaded, so the run does not demonstrate skill use.")
        score = min(score, 2)

    return Grade(score == 4, score, 4, feedback or ["Process looks right."])


def grade_sandbox(resolve_fn: Callable[..., Path]) -> Grade:
    """6 points, all-or-nothing: block every attack *and* still serve real paths."""

    with tempfile.TemporaryDirectory() as tmp:
        root = build_attack_workspace(Path(tmp))
        attacks = run_attacks(resolve_fn, root)
        legitimate = run_legitimate(resolve_fn, root)

    problems = [
        f"Sandbox escape via {row['attack']}: {row['detail']}" for row in attacks if not row["blocked"]
    ]
    problems += [
        f"Legitimate path '{row['case']}' was refused: {row['detail']}"
        for row in legitimate
        if not row["allowed"]
    ]
    if problems:
        return Grade(False, 0, 6, problems)
    return Grade(True, 6, 6, [f"All {len(attacks)} attacks blocked, all {len(legitimate)} real paths served."])


def grade_run(
    answer: dict[str, Any] | None,
    registry: ToolRegistry,
    resolve_fn: Callable[..., Path],
    *,
    require_skill: bool,
) -> Grade:
    parts = [
        grade_answer(answer),
        grade_process(registry, require_skill=require_skill),
        grade_sandbox(resolve_fn),
    ]
    score = sum(part.score for part in parts)
    feedback = [item for part in parts for item in part.feedback]
    # A run that leaks outside the sandbox fails regardless of its answer.
    passed = all(part.passed for part in parts)
    return Grade(passed, score, TOTAL_POINTS, feedback)
