"""Deterministic grading for the exact-arithmetic comparison."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any

from task import EXPECTED_ANSWER, REQUIRED_CALCULATOR_RESULTS


@dataclass
class Grade:
    passed: bool
    score: int
    feedback: list[str]


def extract_json_answer(text: str) -> dict[str, str] | None:
    """Extract ``answer`` from JSON or common weak-model near-JSON variants."""

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "answer" in value:
            return {"answer": str(value["answer"]).strip()}

    for candidate in re.findall(r"\{[^{}]{1,300}\}", text, re.DOTALL):
        try:
            value = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            continue
        if isinstance(value, dict) and "answer" in value:
            return {"answer": str(value["answer"]).strip()}

    fallback = re.search(r"[\"']?answer[\"']?\s*[:=]\s*[\"']?(\d+)", text, re.IGNORECASE)
    return {"answer": fallback.group(1)} if fallback else None


def grade_answer(answer: dict[str, str] | None) -> Grade:
    if answer is None:
        return Grade(False, 0, ["No answer JSON was found."])
    feedback: list[str] = []
    score = 0
    if answer.get("answer") == EXPECTED_ANSWER["answer"]:
        score += 8
    else:
        feedback.append("The last six digits are incorrect.")
    if set(answer) == {"answer"} and re.fullmatch(r"\d{6}", answer.get("answer", "")):
        score += 2
    else:
        feedback.append("Return exactly one field named answer containing six digits.")
    return Grade(score == 10, score, feedback or ["Exact answer matched."])


def grade_react_run(answer: dict[str, str] | None, tool_history: list[dict[str, Any]]) -> Grade:
    base = grade_answer(answer)
    feedback = list(base.feedback)
    calculator_results = {
        event.get("output")
        for event in tool_history
        if event.get("tool") == "calculate"
    }
    completed_two_stage_calculation = REQUIRED_CALCULATOR_RESULTS <= calculator_results
    process_score = 2 if completed_two_stage_calculation else 0
    if not completed_two_stage_calculation:
        feedback.append("The trace must calculate both the seed and the branched final code.")
    return Grade(base.passed and process_score == 2, base.score + process_score, feedback)
