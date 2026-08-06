"""A small, explicit ReAct loop in the style of Thought/Action/Observation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from grader import extract_json_answer, grade_answer
from task import EXPECTED_ANSWER, REQUIRED_CALCULATOR_RESULTS
from tools import ToolEnvironment
from zhipu_client import ChatClient, DEFAULT_MODEL


REACT_SYSTEM_PROMPT = """
You are a ReAct agent solving a branching exact-arithmetic task. Mental
estimation is not reliable enough; calculate the seed, observe it, select the
correct branch, and calculate the final code.

At each turn, produce a short Thought and exactly ONE Action on its own line:

Thought: why the next action is needed
Action: Calculate[numeric expression]
Action: Finish[{"answer":"......"}]

You may use only one Action per turn. After Calculate, the runtime returns an
Observation. Use that exact value in the next turn.

Rules:
- First use pow(base, exponent, 1000000) to calculate S in one action.
- Read the returned Observation and decide whether S is even or odd.
- Use a second Calculate action for only the matching branch formula.
- The final answer must contain exactly six digits; preserve leading zeroes.
- Never guess. Call Finish only after Calculate returns the exact result.
- Keep every Thought concise; the trace is for task control, not hidden reasoning.
""".strip()


ACTION_RE = re.compile(
    r"^\s*Action\s*:\s*(Calculate|Finish)\s*"
    r"(?:\[(.*?)\]|\((.*?)\))\s*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


@dataclass
class Action:
    name: str
    argument: str


@dataclass
class ReactStep:
    index: int
    model_text: str
    action: Action | None
    observation: str | None


@dataclass
class ReactResult:
    answer: dict[str, str] | None
    final_text: str
    steps: list[ReactStep] = field(default_factory=list)
    stopped_reason: str = ""


def parse_action(model_text: str) -> Action | None:
    """Return the first valid ReAct action line from a model response."""

    match = ACTION_RE.search(model_text)
    if not match:
        return None
    argument = match.group(2) if match.group(2) is not None else match.group(3)
    return Action(name=match.group(1).title(), argument=argument.strip())


class ReactAgent:
    def __init__(
        self,
        client: ChatClient,
        tools: ToolEnvironment,
        model: str = DEFAULT_MODEL,
        max_steps: int = 6,
    ) -> None:
        self.client = client
        self.tools = tools
        self.model = model
        self.max_steps = max_steps

    def run(self, task_prompt: str) -> ReactResult:
        messages = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt},
        ]
        steps: list[ReactStep] = []

        for index in range(1, self.max_steps + 1):
            model_text = self.client.chat(
                messages=messages,
                model=self.model,
                temperature=0.2,
                max_tokens=650,
            )
            action = parse_action(model_text)
            messages.append({"role": "assistant", "content": model_text})

            if action is None:
                # Weak models sometimes emit a bare final JSON without Finish.
                # Treat it as a candidate Finish, then apply all normal gates.
                candidate = extract_json_answer(model_text)
                if candidate is not None:
                    action = Action("Finish", model_text)
                else:
                    observation = (
                        "Format error: output exactly one Action line using "
                        "Calculate[...] or Finish[{\"answer\":\"......\"}]."
                    )
                    steps.append(ReactStep(index, model_text, None, observation))
                    messages.append({"role": "user", "content": f"Observation: {observation}"})
                    continue

            if action.name.lower() == "finish":
                answer = extract_json_answer(action.argument) or extract_json_answer(model_text)
                if answer is None:
                    observation = "Finish error: provide a valid JSON object with one answer field."
                    steps.append(ReactStep(index, model_text, action, observation))
                    messages.append({"role": "user", "content": f"Observation: {observation}"})
                    continue

                finish_errors: list[str] = []
                calculator_results = {
                    event["output"]
                    for event in self.tools.history
                    if event["tool"] == "calculate"
                }
                if not REQUIRED_CALCULATOR_RESULTS <= calculator_results:
                    finish_errors.append(
                        "calculate the seed first, observe its parity, then calculate the selected branch"
                    )
                if not re.fullmatch(r"\d{6}", answer.get("answer", "")):
                    finish_errors.append("answer must contain exactly six digits")
                answer_grade = grade_answer(answer)
                if not answer_grade.passed:
                    finish_errors.extend(answer_grade.feedback)
                if finish_errors:
                    observation = "Finish blocked by verifier: " + "; ".join(dict.fromkeys(finish_errors))
                    steps.append(ReactStep(index, model_text, action, observation))
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Observation: {observation}\n"
                                "Correct the calculation or answer, then continue with exactly one Action."
                            ),
                        }
                    )
                    continue
                steps.append(ReactStep(index, model_text, action, None))
                return ReactResult(answer, model_text, steps, "finish_action")

            observation = self.tools.execute(action.name, action.argument)
            steps.append(ReactStep(index, model_text, action, observation))
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Observation: {observation}\n"
                        "Continue with one concise Thought and exactly one Action."
                    ),
                }
            )

        return ReactResult(
            answer=None,
            final_text="",
            steps=steps,
            stopped_reason=f"max_steps_{self.max_steps}",
        )
