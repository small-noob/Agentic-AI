"""The multi-tool ReAct loop. Provided complete — lesson 2 is about the tools.

Lesson 1 parsed a single action shape, ``Calculate[expr]``. With several tools
the action needs a name *and* structured arguments, so the protocol becomes:

    Thought: ...
    Action: read_file
    Action Input: {"path": "policy.json"}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from registry import ToolRegistry
from zhipu_client import ChatClient, DEFAULT_MODEL

SYSTEM_TEMPLATE = """
You are a tool-using audit agent. You cannot see the data directly; every fact
must come from a tool Observation.

Available tools:
{tools}
{skills_block}
Respond with exactly one Thought and one Action per turn:

Thought: one short sentence about the next step
Action: tool_name
Action Input: {{"argument": "value"}}

Action Input must be a single JSON object on one line. After each Action the
runtime replies with an Observation. Use the observed values verbatim.

When every value is known, submit:

Action: finish
Action Input: {{"suspect":"Bxxxx","violations":0,"code":"xxxxxx"}}

Rules:
- One Action per turn. Never invent an Observation.
- Never state a number you have not read from a file or computed with calculate.
- Paths are relative to the workspace root. The sandbox rejects anything outside it.
- The code must contain exactly six digits, preserving leading zeroes.
""".strip()

SKILLS_TEMPLATE = """
Available skills (procedures you can load on demand — read one before improvising):
{index}
"""

ACTION_RE = re.compile(r"^[ \t]*Action[ \t]*:[ \t]*([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
ACTION_INPUT_RE = re.compile(
    r"^[ \t]*Action[ \t]*Input[ \t]*:[ \t]*(.+?)(?=\n[ \t]*(?:Thought|Action|Observation)[ \t]*:|\Z)",
    re.MULTILINE | re.DOTALL,
)
INLINE_ARGS_RE = re.compile(r"^[ \t]*Action[ \t]*:[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*(\{.*)", re.MULTILINE | re.DOTALL)


@dataclass
class Action:
    name: str
    arguments: dict[str, Any]
    raw_input: str = ""


@dataclass
class Step:
    index: int
    model_text: str
    action: Action | None
    observation: str | None


@dataclass
class AgentResult:
    answer: dict[str, Any] | None
    steps: list[Step] = field(default_factory=list)
    stopped_reason: str = ""


def _decode_arguments(raw: str, tool_name: str, registry: ToolRegistry) -> dict[str, Any] | str:
    """Return parsed arguments, or an error string to feed back as Observation."""

    text = raw.strip().strip("`").strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()

    start = text.find("{")
    if start != -1:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

    # Weak models often pass a bare value for single-argument tools.
    spec = registry.tools.get(tool_name)
    if spec is not None and len(spec.parameters["required"]) == 1:
        only = spec.parameters["required"][0]
        if spec.parameters["properties"][only]["type"] == "string" and text:
            return {only: text.strip('"').strip("'")}

    return 'Format error: Action Input must be a JSON object, e.g. {"path": "policy.json"}.'


def parse_action(model_text: str, registry: ToolRegistry) -> Action | str | None:
    """Parse one action, or return an error string, or None when absent."""

    inline = INLINE_ARGS_RE.search(model_text)
    if inline:
        decoded = _decode_arguments(inline.group(2), inline.group(1), registry)
        if isinstance(decoded, str):
            return decoded
        return Action(inline.group(1), decoded, inline.group(2).strip())

    action_match = ACTION_RE.search(model_text)
    if not action_match:
        return None

    name = action_match.group(1)
    input_match = ACTION_INPUT_RE.search(model_text, action_match.end())
    if not input_match:
        if name == "finish":
            return "Format error: finish needs an Action Input JSON object with suspect, violations and code."
        spec = registry.tools.get(name)
        if spec is not None and not spec.parameters["required"]:
            return Action(name, {}, "")
        return f'Format error: {name} needs an "Action Input:" line with a JSON object.'

    decoded = _decode_arguments(input_match.group(1), name, registry)
    if isinstance(decoded, str):
        return decoded
    return Action(name, decoded, input_match.group(1).strip())


class ToolAgent:
    def __init__(
        self,
        client: ChatClient,
        registry: ToolRegistry,
        verifier,
        skill_index: str = "",
        model: str = DEFAULT_MODEL,
        max_steps: int = 12,
    ) -> None:
        self.client = client
        self.registry = registry
        self.verifier = verifier
        self.skill_index = skill_index
        self.model = model
        self.max_steps = max_steps

    def system_prompt(self) -> str:
        skills_block = SKILLS_TEMPLATE.format(index=self.skill_index) if self.skill_index else "\n"
        return SYSTEM_TEMPLATE.format(tools=self.registry.describe(), skills_block=skills_block)

    def run(self, task_prompt: str) -> AgentResult:
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": task_prompt},
        ]
        steps: list[Step] = []

        def observe(index: int, text: str, action: Action | None, observation: str) -> None:
            steps.append(Step(index, text, action, observation))
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation: {observation}\nContinue with one Thought and one Action.",
                }
            )

        for index in range(1, self.max_steps + 1):
            model_text = self.client.chat(
                messages=messages, model=self.model, temperature=0.2, max_tokens=700
            )
            messages.append({"role": "assistant", "content": model_text})
            parsed = parse_action(model_text, self.registry)

            if parsed is None:
                observe(
                    index,
                    model_text,
                    None,
                    'Format error: emit one "Action:" line and one "Action Input:" JSON line.',
                )
                continue
            if isinstance(parsed, str):
                observe(index, model_text, None, parsed)
                continue

            if parsed.name == "finish":
                problems = self.verifier(parsed.arguments, self.registry)
                if problems:
                    observe(
                        index,
                        model_text,
                        parsed,
                        "finish blocked by verifier: " + "; ".join(problems),
                    )
                    continue
                steps.append(Step(index, model_text, parsed, None))
                return AgentResult(parsed.arguments, steps, "finish_action")

            observe(index, model_text, parsed, self.registry.call(parsed.name, parsed.arguments))

        return AgentResult(None, steps, f"max_steps_{self.max_steps}")
