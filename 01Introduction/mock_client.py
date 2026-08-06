"""No-cost deterministic client for classroom setup and automated tests."""

from __future__ import annotations


class ScriptedMockClient:
    def __init__(self) -> None:
        self.react_index = 0
        self.react_responses = [
            (
                "Thought: I first need the exact seed before choosing a branch.\n"
                "Action: Calculate[pow(20250807,123457,1000000)]"
            ),
            (
                "Thought: S is 730807, which is odd, so I must use the odd branch.\n"
                "Action: Calculate[(730807 * 2025 + 271828) % 1000000]"
            ),
            (
                "Thought: The second observation is the exact final code.\n"
                "Action: Finish[{\"answer\":\"156003\"}]"
            ),
        ]

    def chat(self, messages, model, temperature=0.2, max_tokens=900) -> str:
        system = messages[0]["content"] if messages else ""
        if "DIRECT_BASELINE" in system:
            return '{"answer":"482731"}'
        if self.react_index >= len(self.react_responses):
            return "Thought: I should calculate exactly.\nAction: Calculate[1+1]"
        response = self.react_responses[self.react_index]
        self.react_index += 1
        return response
