"""The audit challenge. The data lives on disk, never in the prompt."""

from __future__ import annotations

from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = LESSON_ROOT / "workspace"
SKILLS_DIR = LESSON_ROOT / "skills"
STARTER_SKILLS_DIR = LESSON_ROOT / "skills_starter"

TASK_PROMPT = """
Audit the door-access records for the badge system in your workspace.

The workspace contains the access policy, the employee roster, and one month of
raw access logs. None of that data is in this message — read it with your tools.

Produce three things:

1. suspect     — the badge_id responsible for the most policy violations
2. violations  — the total number of violating records across all badges
3. code        — the six-digit report code defined by the policy file

Also write a short report to 'reports/audit.md' containing the suspect badge_id.

Finish with exactly this JSON shape:
{"suspect":"Bxxxx","violations":0,"code":"xxxxxx"}

Rules:
1. The policy file is the only authority on what counts as a violation.
2. Never estimate a count or a code; read files and use the calculator.
3. The code must contain exactly six digits, keeping leading zeroes.
""".strip()

EXPECTED_ANSWER = {"suspect": "B1005", "violations": 11, "code": "594621"}

# Files the agent must actually open for the process score.
REQUIRED_READS = {"policy.json", "employees.json", "logs/access_2026-08.csv"}
REPORT_PATH = "reports/audit.md"
