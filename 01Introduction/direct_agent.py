"""One-shot baseline: same question, no calculator or second attempt."""

from __future__ import annotations

from zhipu_client import ChatClient, DEFAULT_MODEL


DIRECT_SYSTEM_PROMPT = """
DIRECT_BASELINE
Answer the user's exact-arithmetic question in one model response. You have no
calculator, code execution, tools, or second attempt. Follow the requested JSON
format and do not claim that you used an unavailable tool.
""".strip()


def run_direct(client: ChatClient, task_prompt: str, model: str = DEFAULT_MODEL) -> str:
    return client.chat(
        messages=[
            {"role": "system", "content": DIRECT_SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt},
        ],
        model=model,
        temperature=0.2,
        max_tokens=300,
    )
