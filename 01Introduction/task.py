"""The same branching exact-arithmetic challenge shown to Direct and ReAct."""

TASK_PROMPT = """
An access controller generates a six-digit code in two stages:

1. Compute S = 20250807^123457 mod 1000000.
2. Observe S, then choose exactly one branch:
   - If S is even: C = (S * 2026 + 314159) mod 1000000.
   - If S is odd:  C = (S * 2025 + 271828) mod 1000000.
3. The answer is C written as six digits.

Return exactly one JSON object in this form:
{"answer":"......"}

Rules:
1. The answer must contain exactly six digits; keep leading zeroes if needed.
2. Do not return an estimate or an explanation inside the JSON object.
""".strip()


EXPECTED_ANSWER = {"answer": "156003"}
REQUIRED_CALCULATOR_RESULTS = {"730807", "156003"}
