"""No-cost deterministic client for classroom setup and automated tests.

Two scripted transcripts, selected by whether the system prompt advertises any
skills. They encode the contrast the lesson is built around: without the
procedure the agent skips the roster and reports a plausible but wrong count.
"""

from __future__ import annotations

NOSKILL_SCRIPT = [
    'Thought: I should see what is in the workspace.\nAction: list_files\nAction Input: {"path": "."}',
    'Thought: The log is the interesting file.\nAction: read_file\nAction Input: {"path": "logs/access_2026-08.csv"}',
    'Thought: B1005 stands out at night, that is probably all of it.\n'
    'Action: finish\nAction Input: {"suspect":"B1005","violations":7,"code":"123456"}',
    'Thought: I should check the policy for the code formula.\nAction: read_file\nAction Input: {"path": "policy.json"}',
    'Thought: Compute the code from my count.\nAction: calculate\nAction Input: {"expression": "(7 * 9176 + 1005 * 31337) % 1000000"}',
    'Thought: Write the report.\nAction: write_file\n'
    'Action Input: {"path": "reports/audit.md", "content": "# Access audit\\n\\nSuspect: B1005\\n"}',
    'Thought: Submit.\nAction: finish\nAction Input: {"suspect":"B1005","violations":7,"code":"557917"}',
]

SKILL_SCRIPT = [
    'Thought: An audit skill is listed; load the procedure before improvising.\n'
    'Action: load_skill\nAction Input: {"name": "audit_access_log"}',
    'Thought: The procedure says to learn the real filenames first.\nAction: list_files\nAction Input: {"path": "."}',
    'Thought: Read the policy to learn the rules and the code formula.\nAction: read_file\nAction Input: {"path": "policy.json"}',
    'Thought: The roster decides clearance and status.\nAction: read_file\nAction Input: {"path": "employees.json"}',
    'Thought: Now the raw records.\nAction: read_file\nAction Input: {"path": "logs/access_2026-08.csv"}',
    'Thought: 11 violating records, B1005 has 7 of them; compute the code exactly.\n'
    'Action: calculate\nAction Input: {"expression": "(11 * 9176 + 1005 * 31337) % 1000000"}',
    'Thought: Write the report the task asked for.\nAction: write_file\n'
    'Action Input: {"path": "reports/audit.md", "content": "# Access audit\\n\\nSuspect: B1005\\nViolations: 11\\n"}',
    'Thought: Every value came from an Observation.\n'
    'Action: finish\nAction Input: {"suspect":"B1005","violations":11,"code":"594621"}',
]


class ScriptedMockClient:
    def __init__(self) -> None:
        self.index = 0

    def chat(self, messages, model, temperature=0.2, max_tokens=900) -> str:
        system = messages[0]["content"] if messages else ""
        script = SKILL_SCRIPT if "Available skills" in system else NOSKILL_SCRIPT
        if self.index >= len(script):
            return 'Thought: Nothing left to do.\nAction: list_files\nAction Input: {"path": "."}'
        response = script[self.index]
        self.index += 1
        return response
