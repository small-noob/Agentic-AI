"""All the machinery for the Memory Lab, in reading order. Nothing here is a TODO.

The notebook does `from memory_lab import *` and teaches; this file holds the
gears. Sections, top to bottom:

    sandbox / calculator / registry / action parser / workspace tools
        chapter 2's toolset, embedded verbatim (lesson 2 is notebook-only
        now, so the files live here instead of being imported across folders)
    zhipu client · tokens      the live API client and the budget arithmetic
    sessions                   Part A's two sessions, Part B's transcript, all ground truth
    memory store               the JSONL store the pipeline writes
    trace display · react loop the Part A harness
    memory policy              the class the notebook's four TODO cells bind onto
    grader · pipeline · flows  scoring, the four steps, the A/B run flows

memory_agent.py (next to this file) is Part A's reference pipeline - it
imports from this module and is NOT for reading before the debrief.
"""

from __future__ import annotations

import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = LESSON_ROOT / "workspace"
RUNS_ROOT = LESSON_ROOT / "runs"


# ══════════════════════════════════════════════════════════════════════════
# ── section: sandbox — every file path walks through this door (chapter 2, embedded)
# ══════════════════════════════════════════════════════════════════════════

from pathlib import Path


class SandboxError(Exception):
    """Raised when a requested path would leave the sandbox root."""


MAX_PATH_LENGTH = 200


def resolve_safe_path(root: str | Path, user_path: str, *, must_exist: bool = False) -> Path:
    """Resolve ``user_path`` relative to ``root`` and refuse anything that escapes.

    The check happens *after* ``resolve()`` so that symlinks pointing outside
    the root are caught too — a purely textual ``".." not in path`` check would
    miss them.
    """

    if not isinstance(user_path, str):
        raise SandboxError("Path must be a string")
    if not user_path.strip():
        raise SandboxError("Path must not be empty")
    if "\x00" in user_path:
        raise SandboxError("Path must not contain NUL bytes")
    if len(user_path) > MAX_PATH_LENGTH:
        raise SandboxError(f"Path is longer than {MAX_PATH_LENGTH} characters")
    if user_path.startswith("~"):
        raise SandboxError("Home-directory expansion is not allowed")

    candidate = Path(user_path)
    if candidate.is_absolute() or candidate.drive:
        raise SandboxError("Absolute paths are not allowed; use a path relative to the workspace")

    root_resolved = Path(root).resolve()
    resolved = (root_resolved / candidate).resolve()

    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise SandboxError(f"Path escapes the workspace sandbox: {user_path}")

    if must_exist and not resolved.exists():
        raise SandboxError(f"No such file inside the workspace: {user_path}")

    return resolved


def relative_to_root(root: str | Path, resolved: Path) -> str:
    """Display form of a resolved path, so tool output never leaks host paths."""

    return resolved.relative_to(Path(root).resolve()).as_posix() or "."


# ══════════════════════════════════════════════════════════════════════════
# ── section: calculator — the safe calculator (chapter 2, embedded)
# ══════════════════════════════════════════════════════════════════════════

import ast
import operator
import re

BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_calculate(expression: str) -> int | float:
    """Evaluate numeric arithmetic and the three-argument modular ``pow`` only."""

    def visit(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id != "pow":
                raise ValueError("Only pow(base, exponent, modulus) is allowed")
            if node.keywords or len(node.args) != 3:
                raise ValueError("Use exactly pow(base, exponent, modulus)")
            base, exponent, modulus = (visit(arg) for arg in node.args)
            if not all(isinstance(value, int) for value in (base, exponent, modulus)):
                raise ValueError("pow arguments must be integers")
            if exponent < 0 or exponent > 10**9:
                raise ValueError("Exponent is outside the safe range")
            if modulus <= 0 or modulus > 10**12:
                raise ValueError("Modulus is outside the safe range")
            if abs(base) > 10**12:
                raise ValueError("Base is outside the safe range")
            return pow(base, exponent, modulus)
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("For large powers, use pow(base, exponent, modulus)")
            value = BINARY_OPS[type(node.op)](left, right)
            if abs(value) > 10**15:
                raise ValueError("Intermediate result is too large")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            return UNARY_OPS[type(node.op)](visit(node.operand))
        raise ValueError("Only numeric arithmetic is allowed")

    if len(expression) > 240:
        raise ValueError("Expression is too long")
    return visit(ast.parse(expression, mode="eval"))


def normalize_expression(expression: str) -> str:
    """Rewrite the notations weak models reach for into calculator syntax."""

    expression = expression.strip().strip("`")
    expression = expression.replace("×", "*").replace("÷", "/")
    expression = re.sub(r"\bmod\b", "%", expression, flags=re.IGNORECASE)
    modular_power = re.fullmatch(r"\s*([+-]?\d+)\s*\^\s*(\d+)\s*%\s*(\d+)\s*", expression)
    if modular_power:
        base, exponent, modulus = modular_power.groups()
        return f"pow({base},{exponent},{modulus})"
    return expression


# ══════════════════════════════════════════════════════════════════════════
# ── section: registry — the tool registry and its call history (chapter 2, embedded)
# ══════════════════════════════════════════════════════════════════════════

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


class ToolError(Exception):
    """A tool refused the call. The message is fed back as an Observation."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., str]

    def signature_line(self) -> str:
        parts = []
        for arg, schema in self.parameters["properties"].items():
            required = arg in self.parameters["required"]
            label = f"{arg}: {schema['type']}" + ("" if required else " (optional)")
            parts.append(label)
        return f"{self.name}({', '.join(parts)}) — {self.description}"


def _build_schema(func: Callable[..., Any], param_docs: dict[str, str]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    # Resolved rather than read off the signature: `from __future__ import
    # annotations` turns every hint into a string.
    hints = get_type_hints(func)
    for name, param in inspect.signature(func).parameters.items():
        annotation = hints.get(name)
        if annotation is None:
            raise TypeError(f"Tool '{func.__name__}' parameter '{name}' needs a type hint")
        if annotation not in JSON_TYPES:
            raise TypeError(f"Tool '{func.__name__}' parameter '{name}' has an unsupported type")
        properties[name] = {"type": JSON_TYPES[annotation]}
        if name in param_docs:
            properties[name]["description"] = param_docs[name]
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            properties[name]["default"] = param.default
    return {"type": "object", "properties": properties, "required": required}


@dataclass
class ToolRegistry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    max_output_chars: int = 4000

    def tool(self, description: str, **param_docs: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register the decorated function as a tool and return it unchanged."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            spec = ToolSpec(
                name=func.__name__,
                description=description,
                parameters=_build_schema(func, param_docs),
                func=func,
            )
            self.tools[spec.name] = spec
            return func

        return decorator

    def names(self) -> list[str]:
        return sorted(self.tools)

    def describe(self) -> str:
        """The tool catalogue injected into the system prompt."""

        return "\n".join(f"- {self.tools[name].signature_line()}" for name in self.names())

    def _coerce(self, spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        schema = spec.parameters
        unknown = set(arguments) - set(schema["properties"])
        if unknown:
            raise ToolError(
                f"Unknown argument(s) {sorted(unknown)} for {spec.name}. "
                f"Expected: {sorted(schema['properties'])}"
            )
        missing = [name for name in schema["required"] if name not in arguments]
        if missing:
            raise ToolError(f"Missing required argument(s) {missing} for {spec.name}")

        coerced: dict[str, Any] = {}
        for name, value in arguments.items():
            expected = schema["properties"][name]["type"]
            if expected == "string":
                coerced[name] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            elif expected == "integer":
                try:
                    coerced[name] = int(value)
                except (TypeError, ValueError):
                    raise ToolError(f"Argument '{name}' of {spec.name} must be an integer") from None
            elif expected == "number":
                try:
                    coerced[name] = float(value)
                except (TypeError, ValueError):
                    raise ToolError(f"Argument '{name}' of {spec.name} must be a number") from None
            else:
                coerced[name] = bool(value)
        return coerced

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool by name and always return a string Observation."""

        spec = self.tools.get(name)
        if spec is None:
            result = f"Unknown tool '{name}'. Available tools: {', '.join(self.names())}"
            self.history.append({"tool": name, "arguments": arguments, "output": result, "ok": False})
            return result

        try:
            output = str(spec.func(**self._coerce(spec, arguments)))
            ok = True
        except ToolError as exc:
            output, ok = f"Tool error: {exc}", False
        except Exception as exc:  # a student tool must never kill the loop
            output, ok = f"Tool error: {type(exc).__name__}: {exc}", False

        if len(output) > self.max_output_chars:
            output = output[: self.max_output_chars] + f"\n...[truncated to {self.max_output_chars} chars]"

        self.history.append({"tool": name, "arguments": arguments, "output": output, "ok": ok})
        return output

    def called(self, name: str) -> bool:
        return any(event["tool"] == name and event["ok"] for event in self.history)


# ══════════════════════════════════════════════════════════════════════════
# ── section: zhipu client — the live API client, with per-purpose call accounting
# ══════════════════════════════════════════════════════════════════════════

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4-flash-250414"

PURPOSES = ("agent", "extract", "reconcile", "revoke", "compact")


@dataclass
class ChatResponse:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def __str__(self) -> str:
        return self.text


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 700,
        purpose: str = "agent",
    ) -> ChatResponse: ...


@dataclass
class CallLog:
    """Per-purpose API accounting, reported at the end of a run."""

    calls: Counter = field(default_factory=Counter)
    prompt_tokens: Counter = field(default_factory=Counter)

    def record(self, purpose: str, response: ChatResponse) -> None:
        self.calls[purpose] += 1
        self.prompt_tokens[purpose] += response.prompt_tokens or 0

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())

    @property
    def total_prompt_tokens(self) -> int:
        return sum(self.prompt_tokens.values())

    def summary(self) -> str:
        if not self.calls:
            return "no API calls"
        parts = [
            f"{purpose} x{self.calls[purpose]} ({self.prompt_tokens[purpose]:,}t)"
            for purpose in PURPOSES
            if self.calls[purpose]
        ]
        return (
            f"{self.total_calls} calls, {self.total_prompt_tokens:,} prompt tokens  ["
            + ", ".join(parts)
            + "]"
        )


@dataclass
class ZhipuClient:
    api_key: str
    endpoint: str = DEFAULT_ENDPOINT
    timeout: int = 60
    max_retries: int = 2
    log: CallLog = field(default_factory=CallLog)

    @classmethod
    def from_env(cls) -> "ZhipuClient":
        api_key = os.getenv("ZAI_API_KEY") or os.getenv("ZHIPU_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing API key. Set ZAI_API_KEY (or ZHIPU_API_KEY) in your "
                "shell before starting Jupyter; never hard-code a key in a "
                "cell or a file."
            )
        return cls(api_key=api_key, endpoint=os.getenv("ZAI_BASE_URL", DEFAULT_ENDPOINT))

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 700,
        purpose: str = "agent",
    ) -> ChatResponse:
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False)
                usage = body.get("usage") or {}
                result = ChatResponse(
                    text=content,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
                self.log.record(purpose, result)
                return result
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zhipu API HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError,
                    http.client.HTTPException) as exc:
                # RemoteDisconnected ("remote end closed connection without
                # response") is an HTTPException, not a URLError - observed in
                # a real run killing session 2 mid-flight. Same retry policy.
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Zhipu API connection failed: {exc}") from exc

        raise RuntimeError("Zhipu API request failed after retries")


# ══════════════════════════════════════════════════════════════════════════
# ── section: tokens — token estimates before the call, provider truth after
# ══════════════════════════════════════════════════════════════════════════

import re
from dataclasses import dataclass, field

try:  # pragma: no cover - depends on the environment
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - fallback is the classroom default
    _ENCODING = None


_CJK = re.compile(r"[　-鿿豈-﫿＀-￯]")

# Every provider bills a per-message overhead for the role wrapper. Ignoring it
# makes a 20-message history look ~80 tokens cheaper than it really is.
PER_MESSAGE_OVERHEAD = 4


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENCODING is not None:
        return len(_ENCODING.encode(str(text), disallowed_special=()))
    text = str(text)
    cjk = len(_CJK.findall(text))
    return max(1, cjk + (len(text) - cjk) // 4)


def count_message(message: dict) -> int:
    return count_tokens(message.get("content", "")) + PER_MESSAGE_OVERHEAD


def count_messages(messages: list[dict]) -> int:
    return sum(count_message(m) for m in messages)


def estimator_name() -> str:
    return "tiktoken/cl100k_base" if _ENCODING is not None else "charclass-fallback"


@dataclass
class TokenDrift:
    """Compares local estimates against the provider's reported usage.

    A budget built on an estimator that runs 15% low is a budget that overflows
    in production. This table is what tells you which way yours leans.
    """

    samples: list[tuple[int, int]] = field(default_factory=list)

    def record(self, estimated: int, reported: int | None) -> None:
        if reported:
            self.samples.append((estimated, reported))

    @property
    def mean_relative_error(self) -> float:
        if not self.samples:
            return 0.0
        return sum(abs(e - r) / r for e, r in self.samples) / len(self.samples)

    def summary(self) -> str:
        if not self.samples:
            return f"estimator={estimator_name()} (no provider usage seen)"
        worst = max(self.samples, key=lambda s: abs(s[0] - s[1]))
        return (
            f"estimator={estimator_name()} n={len(self.samples)} "
            f"mean_rel_err={self.mean_relative_error:.1%} "
            f"worst=est {worst[0]} vs actual {worst[1]}"
        )


# ══════════════════════════════════════════════════════════════════════════
# ── section: action parser — the Action / Action Input protocol (chapter 2, embedded)
# ══════════════════════════════════════════════════════════════════════════

import json
import re
from dataclasses import dataclass, field
from typing import Any

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


# ══════════════════════════════════════════════════════════════════════════
# ── section: workspace tools — list/read/write/calculate over the sandbox (chapter 2, embedded)
# ══════════════════════════════════════════════════════════════════════════

from pathlib import Path

MAX_READ_BYTES = 20000
MAX_WRITE_BYTES = 20000
MAX_LISTED_ENTRIES = 100


def build_workspace_tools(root: str | Path, registry: ToolRegistry | None = None) -> ToolRegistry:
    registry = registry if registry is not None else ToolRegistry()
    root = Path(root).resolve()

    @registry.tool(
        "List the files and directories inside a workspace folder.",
        path="Folder relative to the workspace root. Use '.' for the root.",
    )
    def list_files(path: str = ".") -> str:
        try:
            target = resolve_safe_path(root, path, must_exist=True)
        except SandboxError as exc:
            raise ToolError(exc) from exc
        if not target.is_dir():
            raise ToolError(f"'{path}' is a file, not a folder. Use read_file instead.")

        entries = sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name))
        if not entries:
            return f"(empty folder: {relative_to_root(root, target)})"
        lines = []
        for entry in entries[:MAX_LISTED_ENTRIES]:
            marker = "DIR " if entry.is_dir() else "FILE"
            size = "" if entry.is_dir() else f"  {entry.stat().st_size} bytes"
            lines.append(f"{marker}  {relative_to_root(root, entry)}{size}")
        if len(entries) > MAX_LISTED_ENTRIES:
            lines.append(f"...[{len(entries) - MAX_LISTED_ENTRIES} more entries hidden]")
        return "\n".join(lines)

    @registry.tool(
        "Read a UTF-8 text file from the workspace.",
        path="File relative to the workspace root, e.g. 'logs/access_2026-08.csv'.",
        max_bytes=f"Optional read cap, at most {MAX_READ_BYTES}.",
    )
    def read_file(path: str, max_bytes: int = MAX_READ_BYTES) -> str:
        try:
            target = resolve_safe_path(root, path, must_exist=True)
        except SandboxError as exc:
            raise ToolError(exc) from exc
        if target.is_dir():
            raise ToolError(f"'{path}' is a folder. Use list_files instead.")

        cap = max(1, min(int(max_bytes), MAX_READ_BYTES))
        data = target.read_bytes()[: cap + 1]
        text = data.decode("utf-8", errors="replace")
        if len(data) > cap:
            text = text[:cap] + f"\n...[truncated at {cap} bytes; call read_file again with a larger max_bytes]"
        return text

    @registry.tool(
        "Write a UTF-8 text file inside the workspace, creating parent folders as needed.",
        path="Destination relative to the workspace root, e.g. 'reports/audit.md'.",
        content="Full file contents to write.",
    )
    def write_file(path: str, content: str) -> str:
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ToolError(f"Refusing to write more than {MAX_WRITE_BYTES} bytes")
        try:
            target = resolve_safe_path(root, path)
        except SandboxError as exc:
            raise ToolError(exc) from exc
        if target.is_dir():
            raise ToolError(f"'{path}' is an existing folder")
        try:
            target.parent.resolve().relative_to(root)
        except ValueError:
            raise ToolError(f"Parent folder of '{path}' is outside the workspace") from None

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {relative_to_root(root, target)}"

    @registry.tool(
        "Evaluate exact arithmetic. Supports + - * / % and pow(base, exponent, modulus).",
        expression="A numeric expression, e.g. '(11 * 9176 + 1005 * 31337) % 1000000'.",
    )
    def calculate(expression: str) -> str:
        normalized = normalize_expression(expression)
        try:
            value = safe_calculate(normalized)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
            raise ToolError(exc) from exc
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)

    return registry


# ══════════════════════════════════════════════════════════════════════════
# ── section: sessions — the session scripts, the workspace, all ground truth
# ══════════════════════════════════════════════════════════════════════════

from pathlib import Path

# LESSON_ROOT / WORKSPACE_ROOT / RUNS_ROOT are defined at the top of this file.

# ---------------------------------------------------------------------------
# The workspace - Part A's on-disk half
# ---------------------------------------------------------------------------
# Three incident exports. Which one matters was said in conversation only;
# the record count lives in the file only. The two decoys are why a
# tools-only agent cannot just list_files and guess: 0819 is newer, 0805 is
# older, and nothing on disk says which incident the user meant.

_INCIDENT = """incident report {date}
door                        : D3 (ServerRoom)
type                        : tailgating
confirmed violating records : {count}
badge                       : {badge}
status                      : closed
"""

CANONICAL_WORKSPACE = {
    "incident_0805.txt": _INCIDENT.format(date="2026-08-05", count=3, badge="B1002"),
    "incident_0812.txt": _INCIDENT.format(date="2026-08-12", count=7, badge="B1005"),
    "incident_0819.txt": _INCIDENT.format(date="2026-08-19", count=5, badge="B1006"),
}


def reset_workspace() -> None:
    """Restore the workspace to exactly CANONICAL_WORKSPACE.

    Called before every session. A live model will jot what the user said
    into files if the disk lets it sit there (observed in a real run), and
    leftovers would hand the tools-only baseline the conversational facts.
    "Nothing survives between sessions except the memory store" is enforced,
    not hoped for.
    """
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    for path in sorted(WORKSPACE_ROOT.rglob("*"), reverse=True):
        rel = path.relative_to(WORKSPACE_ROOT).as_posix()
        if path.is_file() and rel not in CANONICAL_WORKSPACE:
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()  # only succeeds once emptied
            except OSError:
                pass
    for rel, content in CANONICAL_WORKSPACE.items():
        target = WORKSPACE_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# PART A - session 1: two facts, stated plainly, written nowhere
# ---------------------------------------------------------------------------

SESSION_1 = [
    {
        "turn": 1,
        "role": "user",
        "content": (
            "Morning. Last Tuesday we had a tailgating incident at the ServerRoom. "
            "I exported the confirmed violating records to `incident_0812.txt` in "
            "your workspace - remember which file that is, we'll need it later."
        ),
    },
    {
        "turn": 2,
        "role": "assistant",
        "content": (
            "Noted - the incident file is incident_0812.txt. I'll use that one "
            "when you come back to it."
        ),
    },
    {
        "turn": 3,
        "role": "user",
        "content": (
            "One more thing: the admin office fixed the fine at 200 yuan per "
            "violating record. That's all for today."
        ),
    },
    {
        "turn": 4,
        "role": "assistant",
        "content": "Got it - 200 yuan per violating record. See you.",
    },
]

# ---------------------------------------------------------------------------
# PART A - session 2: one question that needs both halves
# ---------------------------------------------------------------------------

FINAL_REQUEST = (
    "Back. Give me the numbers for that incident: how many confirmed violating "
    "records, and the total fine (record count times the per-record fine). "
    "Return exactly this JSON and nothing else:\n"
    '{"records":"...","total_fine":"..."}'
)

SESSION_2 = [
    {"turn": 1, "role": "user", "content": FINAL_REQUEST},
]

SESSIONS = {1: SESSION_1, 2: SESSION_2}

# records lives only in incident_0812.txt; total_fine = 7 x 200, where 200 was
# only ever said in session 1. Tools can answer one half, memory the other.
EXPECTED_ANSWER = {"records": "7", "total_fine": "1400"}
REQUIRED_CALCULATOR_RESULTS = {"1400"}
REQUIRED_READS = {"incident_0812.txt"}

# What session 1 should leave in the store (the demo pipeline's output).
EXPECTED_DEMO_MEMORY = {
    "incident_file": "incident_0812.txt",
    "fine_per_violation": "200",
}

AGENT_SYSTEM_TEMPLATE = """
You are an audit assistant working across separate sessions. You do not
remember anything by yourself: what you know from earlier sessions arrives in
a [memory] block in your context, and nothing else survives between sessions.
Files live in your workspace - read them with your tools.

Available tools:
{tools}

Respond with exactly one Thought and one Action per turn:

Thought: one short sentence about the next step
Action: tool_name
Action Input: {{"argument": "value"}}

Action Input must be a single JSON object on one line. After each Action the
runtime replies with an Observation. Use the observed values verbatim.

Two more actions end the current turn instead of calling a tool:

Action: respond
Action Input: {{"message": "your short reply to the user"}}

Action: finish
Action Input: {{"records":"...","total_fine":"..."}}

Use respond when the user is briefing you - acknowledge briefly. Use finish
only for the final deliverable, with exactly the JSON shape the user asked for.

Rules:
- One Action per turn. Never invent an Observation.
- Never do arithmetic in your head. Use calculate and read the Observation.
- Never state a value you have not seen in the context, a file, or an Observation.
- Paths are relative to the workspace root. The sandbox rejects anything outside it.
- Never copy what the user said into workspace files. The workspace is shared
  reference material, not your notebook.
- finish is accepted only when the user asks for the final deliverable. Until
  then, end your turn with respond.
""".strip()


# ---------------------------------------------------------------------------
# PART B - the seed store: what "last month" left behind
# ---------------------------------------------------------------------------

SEED_MEMORY = [
    {"key": "incident_file", "value": "incident_0812.txt", "source": "seed", "session": 0},
    {"key": "fine_per_violation", "value": "200", "source": "seed", "session": 0},
    {"key": "report_recipient", "value": "security-team", "source": "seed", "session": 0},
]

# ---------------------------------------------------------------------------
# PART B - the briefing transcript: one long conversation, four TODOs of bait
# ---------------------------------------------------------------------------
# What is planted where:
#   ADD     "logs/access_2026-09.csv"  and  "audit runs on day 1"
#   UPDATE  fine 200 -> 250
#   DELETE  "stop sending the report to security-team"
#   NOOP    "the incident file is still incident_0812.txt"
#   TODO 2  the pasted exporter config contains a credential; one sentence
#           packs two facts
#   TODO 1  the assistant's own turn contains a wrong derived number - user
#           turns only, or the pipeline poisons itself
#   TODO 4  the paste is the L1 trim target; the whole transcript is the L2 one

EXPORTER_ENV_PASTE = """BADGE_EXPORT_SOURCE=door-controller-3
BADGE_EXPORT_FORMAT=csv
BADGE_EXPORT_SCHEDULE=0 2 * * *
BADGE_EXPORT_TIMEZONE=Asia/Singapore
BADGE_EXPORT_RETRIES=3
BADGE_EXPORT_BACKOFF=1.5
ZAI_API_KEY=sk-proj-3f9Qd7LmXb2vNp8KwRt5Yh1Zc4Ja6Ge0Su
EXPORT_BUCKET=s3://badge-exports/monthly
EXPORT_RETENTION_DAYS=90
EXPORT_COMPRESSION=gzip
CHECKSUM_ALGO=sha256
CONTROLLER_HOST=door-ctl.internal
CONTROLLER_PORT=8443
CONTROLLER_TLS=required
CONTROLLER_TIMEOUT=30
ROSTER_SYNC=hourly
ROSTER_SOURCE=hr-system
CLOCK_SOURCE=ntp.internal
CLOCK_MAX_DRIFT_MS=500
LOG_LEVEL=INFO
LOG_FORMAT=json
ALERT_CHANNEL=#facilities
ALERT_ON_FAILURE=true
DEAD_LETTER_DIR=/var/spool/badge-dlq
MAX_BATCH_ROWS=5000
HEALTHCHECK_PATH=/healthz
HEALTHCHECK_INTERVAL=60
DASHBOARD_URL=https://ops.internal/badges
METRICS_PORT=9102
TRACE_SAMPLE_RATE=0.05
PROXY=off
IPV6=off
LOCALE=C.UTF-8
NICE_LEVEL=10
UMASK=0027
TMPDIR=/var/tmp/badge-export
KEEP_PARTIALS=false
VERIFY_ROW_COUNT=true
FAIL_FAST=false
NOTIFY_ON_EMPTY=true"""

TRANSCRIPT = [
    {
        "turn": 1,
        "role": "user",
        "content": (
            "Morning. I'm handing the monthly access audit over to you today - "
            "let me walk you through what changed since last month."
        ),
    },
    {
        "turn": 2,
        "role": "assistant",
        "content": "Ready when you are. I'll keep track as we go.",
    },
    {
        "turn": 3,
        "role": "user",
        "content": (
            "September's raw logs land in `logs/access_2026-09.csv`. That is the "
            "file the audit runs on from now on."
        ),
    },
    {
        "turn": 4,
        "role": "assistant",
        "content": "Noted - the audit reads logs/access_2026-09.csv.",
    },
    {
        "turn": 5,
        "role": "user",
        "content": (
            "The audit itself runs on day 1 of every month, before the management "
            "call. Don't let it slip."
        ),
    },
    {
        "turn": 6,
        "role": "assistant",
        "content": "Understood - audit on day 1, ahead of the call.",
    },
    {
        "turn": 7,
        "role": "user",
        "content": (
            "Finance bumped the fine: it is 250 yuan per violating record now, "
            "not 200. Use the new number for anything you compute."
        ),
    },
    {
        "turn": 8,
        "role": "assistant",
        "content": (
            "Got it - 250 per record. So a ten-record incident would come to "
            "2,000 yuan."  # wrong on purpose: 10 x 250 = 2,500. Extract user
            # turns only, or this mistake ends up in the store.
        ),
    },
    {
        "turn": 9,
        "role": "user",
        "content": (
            "Stop sending the monthly report to security-team - that mailing "
            "list was retired last week. Just drop it."
        ),
    },
    {
        "turn": 10,
        "role": "assistant",
        "content": "Will do - no more copies to security-team.",
    },
    {
        "turn": 11,
        "role": "user",
        "content": (
            "The August incident file is still `incident_0812.txt`, unchanged - "
            "same file as before."
        ),
    },
    {
        "turn": 12,
        "role": "assistant",
        "content": "Right, incident_0812.txt, same as last month.",
    },
    {
        "turn": 13,
        "role": "user",
        "content": (
            "Here's the config block the badge exporter runs with - sanity-check "
            "it when you get a chance:\n\n" + EXPORTER_ENV_PASTE
        ),
    },
    {
        "turn": 14,
        "role": "assistant",
        "content": (
            "Read through it. One flag: the block contains a live-looking "
            "credential - I won't carry that forward anywhere."
        ),
    },
    {
        "turn": 15,
        "role": "user",
        "content": "Good catch, I'll rotate it. Also: the audit covers the ServerRoom and the Lab.",
    },
    {
        "turn": 16,
        "role": "assistant",
        "content": "Noted, both doors are in scope.",
    },
    {
        "turn": 17,
        "role": "user",
        "content": (
            "Oh, and keep the ops dashboard key so you can pull the monthly "
            "numbers - the key is ZAI_API_KEY=sk-proj-3f9Qd7LmXb2vNp8KwRt5Yh1Zc4Ja6Ge0Su. "
            "You'll need it on every run, so hold on to it."
        ),
    },
    {
        "turn": 18,
        "role": "assistant",
        "content": (
            "I'll use it when I pull the numbers, but I won't write that key "
            "into memory or any file."
        ),
    },
    {
        "turn": 19,
        "role": "user",
        "content": (
            "That's everything. First run is next Monday - don't start anything "
            "before then."
        ),
    },
    {
        "turn": 20,
        "role": "assistant",
        "content": "Understood. I have what I need for the handover.",
    },
]

TRANSCRIPT_SESSION_NO = 1  # the seed records are session 0

# What the store must look like after the pipeline has run over TRANSCRIPT.
EXPECTED_PIPELINE_MEMORY = {
    "current": {
        "incident_file": "incident_0812.txt",
        "fine_per_violation": "250",
        "log_file": "logs/access_2026-09.csv",
        "audit_day": "1",
    },
    "superseded": {"fine_per_violation": "200"},
    "revoked_subjects": ["security-team"],
}

# The four facts TODO 1 must surface (values checked loosely by the grader).
EXPECTED_EXTRACTED = {
    "log_file": "logs/access_2026-09.csv",
    "audit_day": "1",
    "fine_per_violation": "250",
    "incident_file": "incident_0812.txt",
}

# Anything matching these must never appear anywhere in the store.
FORBIDDEN_IN_MEMORY = ["sk-proj-", "sk-", "ghp_", "AKIA"]

# TODO 4's demo: assemble this system prompt + the transcript under the budget.
PIPELINE_SYSTEM = (
    "You are the audit assistant. Use the [memory] block and the conversation "
    "to answer the manager's questions."
)
PIPELINE_BUDGET = 600


# ══════════════════════════════════════════════════════════════════════════
# ── section: memory store — the JSONL store - current / superseded / deleted, nothing erased
# ══════════════════════════════════════════════════════════════════════════

import json
from dataclasses import dataclass, field
from pathlib import Path


CURRENT = "current"
SUPERSEDED = "superseded"
DELETED = "deleted"


@dataclass
class MemoryStore:
    """Rooted like a chapter-2 workspace: ``relpath`` is resolved against
    ``root`` through the same ``resolve_safe_path`` every file tool uses.

    The lesson taught last week was "every file tool goes through the sandbox
    door". A memory store is a file the *harness* writes rather than the agent,
    but the rule does not care who is holding the pen - so the store walks
    through the same door. You do not have to write this; you do have to know
    it is there.
    """

    root: Path | None = None
    relpath: str = "memory.jsonl"
    records: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    operations: list[dict] = field(default_factory=list)

    # -- persistence ------------------------------------------------------
    def target(self) -> Path | None:
        """Where this store lives on disk, sandbox-checked. None = in-memory."""
        if self.root is None:
            return None
        return resolve_safe_path(self.root, self.relpath)

    @classmethod
    def load(cls, root: str | Path | None, relpath: str = "memory.jsonl") -> "MemoryStore":
        store = cls(root=Path(root) if root is not None else None, relpath=relpath)
        target = store.target()
        if target is not None and target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    store.records.append(json.loads(line))
        return store

    def save(self) -> None:
        target = self.target()
        if target is None:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(json.dumps(r, ensure_ascii=False) for r in self.records)
        target.write_text(body + ("\n" if body else ""), encoding="utf-8")

    def reset(self) -> None:
        self.records.clear()
        self.rejections.clear()
        self.operations.clear()
        target = self.target()
        if target is not None and target.exists():
            target.unlink()

    # -- reads ------------------------------------------------------------
    def all(self, status: str = CURRENT) -> list[dict]:
        if status == "*":
            return list(self.records)
        return [r for r in self.records if r.get("status") == status]

    def get(self, key: str, status: str = CURRENT) -> dict | None:
        for record in reversed(self.records):
            if record.get("key") == key and record.get("status") == status:
                return record
        return None

    def has(self, key: str, value: str) -> bool:
        return any(
            r.get("key") == key
            and r.get("value") == value
            and r.get("status") == CURRENT
            for r in self.records
        )

    def keys(self, status: str = CURRENT) -> list[str]:
        return [r["key"] for r in self.all(status)]

    # -- writes -----------------------------------------------------------
    def add(self, record: dict) -> dict:
        stored = {
            "key": record["key"],
            "value": record["value"],
            "source": record.get("source", "unknown"),
            "session": record.get("session", 0),
            "status": CURRENT,
        }
        self.records.append(stored)
        self.operations.append({"op": "ADD", "key": stored["key"], "value": stored["value"]})
        return stored

    def supersede(self, key: str, record: dict) -> dict:
        old = self.get(key)
        if old is not None:
            old["status"] = SUPERSEDED
            old["superseded_by"] = record.get("source", "unknown")
        stored = self.add(record)
        self.operations[-1] = {
            "op": "UPDATE",
            "key": key,
            "old": old["value"] if old else None,
            "value": stored["value"],
            "at": stored["source"],
        }
        return stored

    def soft_delete(self, key: str, source: str = "unknown") -> bool:
        record = self.get(key)
        if record is None:
            return False
        record["status"] = DELETED
        record["revoked_by"] = source
        self.operations.append({"op": "DELETE", "key": key, "at": source})
        return True

    def noop(self, key: str) -> None:
        self.operations.append({"op": "NOOP", "key": key})

    def log_rejection(self, record: object, reason: str) -> None:
        self.rejections.append({"record": record, "reason": reason})

    # -- context ----------------------------------------------------------
    def digest(self) -> str:
        """The memory block that goes into the model's context.

        This string is what TODO 4 pays for out of its token budget. Keeping it
        short is the whole reason extraction is worth doing.
        """
        current = self.all(CURRENT)
        if not current:
            return ""
        body = " | ".join(f'{r["key"]}={r["value"]}' for r in current)
        return f"[memory] {body}"

    # -- reporting --------------------------------------------------------
    def report(self, session_no: int) -> str:
        lines = [f"[memory] after session {session_no}"]
        for record in self.records:
            flag = {CURRENT: " ", SUPERSEDED: "~", DELETED: "x"}.get(record["status"], "?")
            lines.append(
                f"  {flag} {record['key']:<18} {record['value']:<28} "
                f"{record['status']:<11} {record['source']}"
            )
        if self.rejections:
            lines.append(f"  rejected {len(self.rejections)} candidate(s):")
            for item in self.rejections:
                shown = json.dumps(item["record"], ensure_ascii=False)
                if len(shown) > 66:
                    shown = shown[:63] + "..."
                lines.append(f"    - {shown}  reason={item['reason']}")
        return "\n".join(lines)

    def leaked_secrets(self, patterns: list[str]) -> list[str]:
        """Every forbidden fragment that made it into the store. Should be empty."""
        blob = json.dumps(self.records, ensure_ascii=False)
        return [p for p in patterns if p in blob]


# ══════════════════════════════════════════════════════════════════════════
# ── section: trace display — terminal rendering (display only, never grading)
# ══════════════════════════════════════════════════════════════════════════

import json
import os
import re
import sys
import textwrap


def _color_enabled() -> bool:
    if os.getenv("FORCE_COLOR"):
        return True
    if os.getenv("NO_COLOR"):
        return False
    return sys.stdout.isatty()


_ON = _color_enabled()


def _c(code: str) -> str:
    return f"\033[{code}m" if _ON else ""


RESET, BOLD, DIM = _c("0"), _c("1"), _c("2")
CYAN, MAGENTA, RED, GREEN, YELLOW, GRAY = (
    _c("36"), _c("35"), _c("31"), _c("32"), _c("33"), _c("90"),
)

WIDTH = 72


def _clip(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text[:limit] + " ..." if len(text) > limit else text


def _rows(text: str, limit: int = 300, width: int = WIDTH - 4) -> list[str]:
    return textwrap.wrap(_clip(text, limit), width) or [""]


def _block(icon: str, color: str, text: str, limit: int = 220) -> None:
    """One icon-labelled entry inside a card; continuation lines align."""
    rows = _rows(text, limit)
    print(f"│ {color}{icon} {rows[0]}{RESET}")
    for row in rows[1:]:
        print(f"│ {color}   {row}{RESET}")


# ---------------------------------------------------------------- cards

def session_banner(session_no: int, policy_name: str, budget: int = 0) -> None:
    bar = "═" * WIDTH
    tail = f" · budget {budget:,}t" if budget > 0 else ""
    print(f"\n{BOLD}{bar}\n SESSION {session_no} · policy={policy_name}{tail}\n{bar}{RESET}")


def user_card(session_no: int, turn_no: int, content: str) -> None:
    print(f"\n{CYAN}{BOLD}🙋 USER (S{session_no}·T{turn_no}){RESET}")
    for row in _rows(content):
        print(f"{CYAN}│{RESET} {row}")


def ladder(lines) -> None:
    """Context-assembly rungs. Compaction is a teaching moment - highlight it."""
    for line in lines:
        text = " ".join(str(line).split())
        if "compact" in text:
            print(f"  {YELLOW}🗜 {text}{RESET}")
        else:
            print(f"  {DIM}⚙ {text}{RESET}")


def model_card(step: int, raw_text: str, parsed) -> None:
    """One ReAct step: the thought, then whatever action was parsed.

    ``parsed`` is the action object (has .name / .arguments), or None when
    the reply failed to parse - then the raw text is shown and the following
    observation line explains the format error.
    """
    print(f"{BOLD}🤖 MODEL · step {step}{RESET}")

    thought = re.search(r"Thought:\s*(.+?)(?=\s*Action\s*:|\Z)", str(raw_text), re.S)
    if thought and thought.group(1).strip():
        _block("💭", GRAY, thought.group(1))

    name = getattr(parsed, "name", None)
    if name == "respond":
        args = parsed.arguments
        message = args.get("message", args) if isinstance(args, dict) else args
        _block("💬", GREEN, f"「{_clip(message, 200)}」")
    elif name == "finish":
        _block("🏁", BOLD, "finish ▸ " + json.dumps(parsed.arguments, ensure_ascii=False), limit=300)
    elif name:
        args = json.dumps(parsed.arguments, ensure_ascii=False)
        _block("🔧", MAGENTA, f"{name} ▸ {_clip(args, 180)}")
    else:
        _block("❓", YELLOW, _clip(raw_text, 220))


# ---------------------------------------------------------- observations

_KINDS = {
    # kind        icon   color         label
    "tool":       ("📎", "",           ""),
    "tool_error": ("❌", "",           ""),
    "format":     ("⚠️", "",           "FORMAT ERROR"),
    "guard":      ("🛑", "",           "GUARD"),
    "verifier":   ("🛑", "",           "VERIFIER"),
}


def observation(text: str, kind: str = "tool") -> None:
    if kind == "tool" and str(text).lstrip().startswith("Tool error"):
        kind = "tool_error"
    icon, _, label = _KINDS.get(kind, _KINDS["tool"])
    color = {
        "tool": DIM,
        "tool_error": RED,
        "format": YELLOW,
        "guard": RED + BOLD,
        "verifier": RED,
    }.get(kind, DIM)
    body = (f"{label} ▸ " if label else "") + _clip(text, 260)
    rows = _rows(body, 300)
    print(f"└ {color}{icon} {rows[0]}{RESET}")
    for row in rows[1:]:
        print(f"     {color}{row}{RESET}")


def turn_end() -> None:
    print(f"{DIM}└ ◀ turn ended (respond){RESET}")


def finish_ok() -> None:
    print(f"{GREEN}{BOLD}└ ✅ finish accepted — verifier passed{RESET}")


def warn(text: str) -> None:
    print(f"  {YELLOW}⚠️ {text}{RESET}")


def overflow(text: str) -> None:
    print(f"  {RED}{BOLD}🛑 CONTEXT OVERFLOW ▸ {text}{RESET}")


# ------------------------------------------------------------- main.py

def run_banner(label: str, budget: int = 0) -> None:
    bar = "#" * WIDTH
    tail = f"   (budget {budget:,}t)" if budget > 0 else ""
    print(f"\n{BOLD}{bar}\n#  {label}{tail}\n{bar}{RESET}")


def verdict(passed: bool, score: int, total: int) -> str:
    color, word = (GREEN, "PASS") if passed else (RED, "FAIL")
    return f"{color}{BOLD}{word}{RESET} — {score}/{total}"


def _stat(icon: str, label: str, value: str, color: str = "") -> None:
    rows = _rows(value, limit=500, width=WIDTH - 18)
    print(f" {icon} {label:<12}{color}{rows[0]}{RESET}")
    for row in rows[1:]:
        print(f"     {'':<12}{color}{row}{RESET}")


def summary_card(*, label: str, budget: int, passed: bool, score: int, total: int,
                 feedback: list, answer, stopped: str, peak: int,
                 compactions: int, rung: int, mem: tuple,
                 api: str = "", drift: str = "",
                 overflow_msg=None, partial_note=None) -> None:
    """The end-of-run report card. Verdict and diagnosis first, stats after."""
    bar = "─" * WIDTH
    print(f"\n{bar}")
    if partial_note is not None:
        print(f" {BOLD}🏆 {label}{RESET}   {YELLOW}{BOLD}NOT GRADED{RESET}")
        print(bar)
        for row in _rows(partial_note, 300, WIDTH - 5):
            print(f" {YELLOW}{row}{RESET}")
    else:
        print(f" {BOLD}🏆 {label}{RESET}   {verdict(passed, score, total)}")
        print(bar)
        mark, colr = ("✓", GREEN) if passed else ("✗", RED)
        for item in feedback:
            rows = _rows(item, 300, WIDTH - 5)
            print(f" {colr}{mark} {rows[0]}{RESET}")
            for row in rows[1:]:
                print(f" {colr}  {row}{RESET}")
    print()

    _stat("📝", "answer", json.dumps(answer, ensure_ascii=False),
          RED + BOLD if answer is None else (GREEN if passed else ""))
    _stat("⏹", "stopped", stopped)
    if budget > 0:
        pct = peak * 100 // budget
        _stat("📐", "context", f"peak {peak:,} / {budget:,}t  ({pct}% of budget)",
              YELLOW if pct >= 95 else "")
    else:
        _stat("📐", "context", f"peak {peak:,}t")
    if compactions or rung:
        _stat("🗜", "compactions", f"{compactions} · highest rung L{rung}", YELLOW)
    cur, sup, dele = mem
    _stat("🧠", "memory", f"{cur} current · {sup} superseded · {dele} deleted",
          DIM if (cur + sup + dele) == 0 else "")
    if api:
        _stat("🌐", "api", api)
    if drift:
        _stat("📏", "estimate", drift, DIM)
    if overflow_msg:
        _stat("🛑", "overflow", overflow_msg, RED + BOLD)


# ══════════════════════════════════════════════════════════════════════════
# ── section: react loop — Part A's loop over the chapter-2 toolset; Assembled / ContextOverflow for TODO 4
# ══════════════════════════════════════════════════════════════════════════

# The react-loop section below renders through "ui.*" - in module
# form that alias simply points back at this module.
ui = sys.modules[__name__]

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any


# Per *user turn*, not per run. The deliverable turn needs read_file,
# calculate and finish, plus slack for a wrong guess and a format retry.
DEFAULT_MAX_STEPS = 6

FORMAT_ERROR_HINT = (
    'Format error: emit one "Action:" line naming a tool (or respond/finish) '
    'and one "Action Input:" line with a JSON object.'
)


# ---------------------------------------------------------------------------
# Parsing helper - shared with student code (TODO 1 and TODO 3 use it too)
# ---------------------------------------------------------------------------


def extract_json_object(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply, tolerantly.

    Weak models emit fenced blocks, trailing prose, and single-quoted dicts.
    Never assume a reply is clean JSON.
    """
    text = str(text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    for candidate in re.findall(r"\{.{1,4000}\}", text, re.DOTALL):
        try:
            value = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


# ---------------------------------------------------------------------------
# Shared types for TODO 4 (used by Part B's pipeline, not by this loop)
# ---------------------------------------------------------------------------


@dataclass
class Assembled:
    """What build_context returns: the messages, their cost, and the rungs."""

    messages: list[dict]
    tokens: int
    ladder: list[str] = field(default_factory=list)


class ContextOverflow(RuntimeError):
    """Raised when the assembled context cannot be brought under budget.

    The harness refuses to send the request. A budget that is merely reported
    is not a budget; this is what makes it real.
    """

    def __init__(self, used: int, budget: int, detail: str = "") -> None:
        super().__init__(
            f"assembled context is {used:,} tokens, budget is {budget:,}"
            + (f" ({detail})" if detail else "")
        )
        self.used = used
        self.budget = budget


# ---------------------------------------------------------------------------
# Trace records
# ---------------------------------------------------------------------------


@dataclass
class TurnRecord:
    session: int
    turn: int
    step: int
    context_tokens: int
    model_text: str
    action: dict | None  # {"name": ..., "arguments": {...}} once parsed
    observation: str | None


@dataclass
class RunResult:
    answer: dict | None = None
    stopped_reason: str = ""
    turns: list[TurnRecord] = field(default_factory=list)
    drift: TokenDrift = field(default_factory=TokenDrift)


def _assemble(system: str, store: Any, history: list[dict]) -> list[dict]:
    """system + [memory] digest (when non-empty) + the session so far."""
    messages = [{"role": "system", "content": system}]
    digest = store.digest()
    if digest:
        messages.append({"role": "system", "content": digest})
    messages.extend(history)
    return messages


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def run_sessions(
    client: Any,
    policy: Any,
    store: Any,
    sessions: dict[int, list[dict]],
    system_prompt: str,
    registry: ToolRegistry,
    verifier=None,
    model: str = "",
    only_session: int | None = None,
    verbose: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
    answer_keys: set[str] | None = None,
    on_session_start=None,
) -> RunResult:
    """Run the scripted sessions in order and return the trace.

    Only the *user* turns are scripted. The agent produces its own assistant
    turns, so the conversation the memory pipeline extracts from is the one
    that really happened. ``registry`` carries the auditable tool-call history
    the verifier and grader read - same object, same audit, as chapter 2.

    ``on_session_start`` is called with the session number before each session
    begins; main.py passes the workspace reset through it.
    """
    result = RunResult()
    kwargs = {"model": model} if model else {}

    ordered = sorted(sessions) if only_session is None else [only_session]

    # finish is only accepted on the last user turn of the last session being
    # run - the turn that asks for the deliverable. Without this guard a
    # chatty model can "finish" during session 1's goodbye and silently skip
    # the rest (a real GLM-4-Flash failure, not a hypothetical).
    final_session = ordered[-1]
    final_turn = max(
        (e["turn"] for e in sessions[final_session] if e["role"] == "user"),
        default=None,
    )
    finish_not_yet = (
        "finish is not accepted yet: the user has not asked for the final "
        "deliverable in this turn. End the turn with respond instead."
    )

    for session_no in ordered:
        if on_session_start is not None:
            on_session_start(session_no)
        history: list[dict] = []
        if verbose:
            ui.session_banner(session_no, policy.name, 0)

        for entry in sessions[session_no]:
            if entry["role"] != "user":
                continue  # assistant turns are generated, not replayed
            history.append({"role": "user", "content": entry["content"]})
            if verbose:
                ui.user_card(session_no, entry["turn"], entry["content"])

            for step in range(1, max_steps + 1):
                messages = _assemble(system_prompt, store, history)
                context_tokens = count_messages(messages)
                if verbose:
                    ui.ladder([f"context {context_tokens:,}t"])

                reply = client.chat(messages, purpose="agent", **kwargs)
                result.drift.record(context_tokens, reply.prompt_tokens)
                text = str(reply)
                history.append({"role": "assistant", "content": text})

                def record(action: dict | None, observation: str | None) -> None:
                    result.turns.append(
                        TurnRecord(session_no, entry["turn"], step, context_tokens,
                                   text, action, observation)
                    )

                def observe(observation: str, tail: str, kind: str = "tool") -> None:
                    history.append({"role": "user", "content": f"Observation: {observation}\n{tail}"})
                    if verbose:
                        ui.observation(observation, kind)

                parsed = parse_action(text, registry)

                if parsed is None:
                    # A model that emits the final JSON without wrapping it in
                    # a finish action still deserves to be graded on it.
                    candidate = extract_json_object(text)
                    if (answer_keys and candidate is not None
                            and answer_keys <= set(candidate)
                            and session_no == final_session
                            and entry["turn"] == final_turn):
                        parsed = _FinishShim(candidate)

                if verbose:
                    # A parse-error string carries no action; show the raw reply.
                    ui.model_card(step, text, None if isinstance(parsed, str) else parsed)

                if parsed is None:
                    record(None, FORMAT_ERROR_HINT)
                    observe(FORMAT_ERROR_HINT, "Continue with one Thought and one Action.",
                            kind="format")
                    continue

                if isinstance(parsed, str):  # parse error with a specific message
                    record(None, parsed)
                    observe(parsed, "Continue with one Thought and one Action.", kind="format")
                    continue

                action_view = {"name": parsed.name, "arguments": parsed.arguments}

                if parsed.name == "respond":
                    if session_no == final_session and entry["turn"] == final_turn:
                        # The mirror of the finish guard: on the deliverable
                        # turn, respond is not an exit.
                        redirect = (
                            "The user asked for the final deliverable this turn. "
                            "Do the work with your tools - list_files if you are "
                            "unsure of a name, read what you need, calculate what "
                            "you must - then submit with finish."
                        )
                        record(action_view, redirect)
                        observe(redirect, "Continue with exactly one Action.", kind="guard")
                        continue
                    record(action_view, None)
                    if verbose:
                        ui.turn_end()
                    break  # the turn is answered; move to the next user turn

                if parsed.name == "finish":
                    if not (session_no == final_session and entry["turn"] == final_turn):
                        record(action_view, finish_not_yet)
                        observe(finish_not_yet, "Continue with exactly one Action.", kind="guard")
                        continue
                    answer = parsed.arguments
                    errors = verifier(answer, registry) if verifier else []
                    if errors:
                        observation = "finish blocked by verifier: " + "; ".join(
                            dict.fromkeys(errors)
                        )
                        record(action_view, observation)
                        observe(observation, "Correct it, then continue with exactly one Action.",
                                kind="verifier")
                        continue
                    result.answer = answer
                    result.stopped_reason = "finish_action"
                    record(action_view, None)
                    if verbose:
                        ui.finish_ok()
                    policy.close_session(client, store, history, session_no)
                    return result

                observation = registry.call(parsed.name, parsed.arguments)
                record(action_view, observation)
                observe(observation, "Continue with one concise Thought and exactly one Action.")
            else:
                if verbose:
                    ui.warn(f"step budget {max_steps} reached for this turn")

        # End of session: the write path. This line IS the A/B comparison -
        # the tools policy does nothing here, the memory policy extracts.
        policy.close_session(client, store, history, session_no)
        if verbose:
            print()
            print(store.report(session_no))

    result.stopped_reason = result.stopped_reason or "sessions_exhausted"
    return result


class _FinishShim:
    """Wraps a bare answer JSON so it flows through the finish branch."""

    name = "finish"

    def __init__(self, arguments: dict) -> None:
        self.arguments = arguments


# ══════════════════════════════════════════════════════════════════════════
# ── section: agent registry — the registry both Part A modes get - nothing new mounted
# ══════════════════════════════════════════════════════════════════════════

from pathlib import Path


def build_agent_registry(workspace_root: str | Path) -> ToolRegistry:
    """Chapter 2's registry: sandboxed list_files / read_file / write_file
    plus calculate. Both Part A modes get this registry and nothing else."""
    return build_workspace_tools(workspace_root)


# ══════════════════════════════════════════════════════════════════════════
# ── section: memory policy — the class your four TODOs bind onto (trim / compact provided)
# ══════════════════════════════════════════════════════════════════════════

import re

# --------------------------------------------------------------------------
# Provided constants. Tune them if you want - they are policy, not law.
# --------------------------------------------------------------------------

# A single message longer than this is a candidate for trimming at L1.
MAX_MESSAGE_TOKENS = 180

# How many recent turns stay verbatim when L2 compacts. The current turn must
# always survive: it is what the pipeline has to act on.
TAIL_KEEP = 4

# A starting point, not a complete list. TODO 2 extends it in the notebook.
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),          # OpenAI / Zhipu style
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),             # AWS access key id
]

# Ways a model crams two facts into one record. Used by TODO 2.
COMPOUND_MARKERS = [" and ", " & ", "; ", "、", "\n"]

# Provided - the compact() helper below uses it. Note how different its job
# is from TODO 1's: extraction keeps only durable facts as structured
# records, while this prompt writes prose and must preserve EVERY concrete
# value in the span. Same model, two uses.
COMPACT_PROMPT = """Summarise this slice of a conversation in at most 110 words.

Preserve every concrete value: file names, amounts, counts, dates, schedules,
and any instruction the user gave. Drop greetings, acknowledgements, and
restatements of intent. Write plain prose, no bullet points."""


class MemoryPolicy:
    """Your memory pipeline. Part B drives these four methods directly."""

    name = "memory(yours)"

    def __init__(self, model: str = "", tail_keep: int = TAIL_KEEP) -> None:
        self.model = model
        self.tail_keep = tail_keep
        self.compactions = 0
        self.max_ladder_rung = 0

    def _kwargs(self) -> dict:
        """Pass this to client.chat(**self._kwargs()) so --model is respected."""
        return {"model": self.model} if self.model else {}

    # ====================================================================
    # TODO 1 - the write path. Answered in the notebook (Part B, TODO 1).
    # ====================================================================
    def write_memory(self, client, conversation: list[dict], session_no: int) -> list[dict]:
        """Turn one whole conversation into a list of candidate memory records."""
        raise NotImplementedError(
            "TODO 1: write_memory - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 1 cell defines and binds it)")

    # ====================================================================
    # TODO 2 - the write gate. Answered in the notebook (Part B, TODO 2).
    # ====================================================================
    def validate_record(self, record: dict, store) -> tuple[bool, str]:
        """Decide whether one candidate record may enter the store."""
        raise NotImplementedError(
            "TODO 2: validate_record - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 2 cell defines and binds it)")

    # ====================================================================
    # TODO 3 - update and forget. Answered in the notebook (Part B, TODO 3).
    # ====================================================================
    def reconcile(self, client, store, records: list[dict], conversation: list[dict],
                  session_no: int) -> None:
        """Apply the accepted records to the store: ADD / UPDATE / DELETE / NOOP."""
        raise NotImplementedError(
            "TODO 3: reconcile - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 3 cell defines and binds it)")

    # ====================================================================
    # TODO 4 - working memory under a budget. Answered in the notebook.
    # ====================================================================
    def build_context(self, client, system: str, store, history: list[dict],
                      budget: int):
        """Assemble messages for one model call under ``budget`` tokens."""
        raise NotImplementedError(
            "TODO 4: build_context - answer in Memory_Lab_Learner.ipynb "
            "(the TODO 4 cell defines and binds it)")

    # ==================================================================
    # Provided. Not a TODO. Both TODO 1 (so the long paste cannot drown
    # the short facts) and TODO 4's L1 rung use this helper.
    # ==================================================================
    def trim_oversized(self, message: dict) -> dict:
        """Shorten one message; do not drop it.

        Returns ``message`` unchanged if it fits MAX_MESSAGE_TOKENS. Otherwise
        keeps the head and the tail (the head carries the framing, the tail
        often the conclusion) and leaves a visible marker, so anyone reading
        the trace can tell a trim happened.
        """
        content = str(message.get("content", ""))
        if count_tokens(content) <= MAX_MESSAGE_TOKENS:
            return message
        lines = content.splitlines()
        head, tail = lines[:10], lines[-3:]
        removed = max(0, len(lines) - len(head) - len(tail))
        shorter = "\n".join(head + [f"[... {removed} lines trimmed ...]"] + tail)
        return {**message, "content": shorter}

    # ==================================================================
    # Provided. Not a TODO. TODO 4's L2 and L3 rungs call this to squeeze
    # several turns into one short note - one API call per use, driven by
    # the provided COMPACT_PROMPT above.
    # ==================================================================
    def compact(self, client, messages: list[dict]) -> str:
        """Several turns in, one short prose note out. Lossy by design -
        which is exactly why your ladder tries the free, lossless trim first."""
        self.compactions += 1
        body = "\n\n".join(f'[{m["role"]}] {m["content"]}' for m in messages)
        reply = client.chat(
            [
                {"role": "system", "content": COMPACT_PROMPT},
                {"role": "user", "content": body},
            ],
            temperature=0.0,
            max_tokens=280,
            purpose="compact",
            **self._kwargs(),
        )
        return f"[compacted {len(messages)} earlier turns] {reply}"

    # ==================================================================
    # Provided. Not a TODO. This is the background write path: it runs once
    # when a session ends, and it is where 1 -> 2 -> 3 connect. Part A's
    # memory mode calls it; Part B's pipeline drives the four methods
    # directly, one step at a time.
    # ==================================================================
    def close_session(self, client, store, conversation: list[dict], session_no: int) -> None:
        candidates = self.write_memory(client, conversation, session_no)

        accepted = []
        for record in candidates:
            ok, reason = self.validate_record(record, store)
            if ok:
                accepted.append(record)
            else:
                store.log_rejection(record, reason)

        self.reconcile(client, store, accepted, conversation, session_no)
        store.save()


# ══════════════════════════════════════════════════════════════════════════
# ── section: grader — Part A PASS/FAIL and the 20-point report card
# ══════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass, field

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


# ══════════════════════════════════════════════════════════════════════════
# ── section: pipeline — the four steps - files saved to runs/, instant feedback after each
# ══════════════════════════════════════════════════════════════════════════

import json
import os
import sys
from pathlib import Path


INITIAL_FILE = "0_initial_memory.jsonl"
FINAL_FILE = "final_memory.jsonl"
STEP_FILES = {
    1: "1_todo1_candidates.json",
    2: "2_todo2_gate.json",
    3: "3_todo3_operations.json",
}
LINEAGE = [INITIAL_FILE, *STEP_FILES.values(), FINAL_FILE]


# ---------------------------------------------------------------- plumbing

def make_policy(implementation: str, model: str):
    if implementation == "starter":
        # The class the notebook binds your answers onto - "starter" works
        # once the TODO cells have run in this kernel.
        return MemoryPolicy(model=model)
    # Lazy import: memory_agent.py imports back from this module.
    from memory_agent import MemoryPolicy as ReferencePolicy

    return ReferencePolicy(model=model)


def _banner(step: str, title: str) -> None:
    print(f"\n{BOLD}── {step} · {title} {'─' * max(0, 46 - len(title))}{RESET}")


def _save(name: str, payload) -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    (RUNS_ROOT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{DIM}  saved -> runs/{name}{RESET}")


def _require(name: str, produced_by: str):
    target = RUNS_ROOT / name
    if not target.exists():
        sys.exit(f"runs/{name} not found - run {produced_by} first.")
    return json.loads(target.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- feedback
# Instant per-step verdicts, printed the moment a step finishes. These are
# hints that mirror the grader; the authoritative score is STEP 4's card.

def _fb(ok, text: str) -> None:
    if ok is True:
        print(f"  {GREEN}✓ {text}{RESET}")
    elif ok is False:
        print(f"  {RED}✗ {text}{RESET}")
    else:
        print(f"  {DIM}· {text}{RESET}")


def _norm(value) -> str:
    return " ".join(str(value).strip().lower().split())


def _feedback1(candidates: list) -> None:
    print(f"\n{BOLD}  feedback (TODO 1){RESET}")
    hit, missing = 0, []
    for key, value in EXPECTED_EXTRACTED.items():
        found = any(
            isinstance(c, dict)
            and (str(c.get("key", "")) == key or _norm(value) in _norm(c.get("value", "")))
            for c in candidates
        )
        hit += found
        if not found:
            missing.append(key)
    _fb(hit == len(EXPECTED_EXTRACTED),
        f"{hit}/{len(EXPECTED_EXTRACTED)} expected facts extracted"
        + (f" - missing: {', '.join(missing)}" if missing else ""))
    if any(isinstance(c, dict) and c.get("key") == "ten_record_total" for c in candidates):
        _fb(False, "the assistant's wrong arithmetic was extracted - "
                   "flatten USER turns only")
    _fb(None, f"{len(candidates)} candidate(s) total (extras are fine; "
              "the gate and reconcile deal with them)")


def _feedback2(accepted: list, rejected: list) -> None:
    print(f"\n{BOLD}  feedback (TODO 2){RESET}")
    leaked = [
        c for c in accepted
        if isinstance(c, dict)
        and any(f in f'{c.get("key", "")} {c.get("value", "")}' for f in FORBIDDEN_IN_MEMORY)
    ]
    if leaked:
        _fb(False, f"A SECRET PASSED THE GATE: {leaked[0].get('key')} - "
                   "one leak makes the whole 6-point item 0")
    else:
        _fb(True, "nothing secret slipped through")
    if rejected:
        reasons = ", ".join(sorted({r["reason"] for r in rejected}))
        _fb(True, f"rejected {len(rejected)} candidate(s): {reasons}")
    else:
        _fb(None, "nothing was rejected this run - fine if extraction was "
                  "clean; the attack-set cell in the notebook is where the "
                  "gate is always exercised")


def _feedback3(store) -> None:
    print(f"\n{BOLD}  feedback (TODO 3){RESET}")
    fine = store.get("fine_per_violation")
    superseded = [r for r in store.all("superseded")
                  if r["key"] == "fine_per_violation" and "200" in _norm(r["value"])]
    _fb(bool(fine and "250" in _norm(fine["value"]) and superseded),
        "UPDATE kept the audit trail (fine 250 current, 200 superseded)")
    deleted = any("security-team" in _norm(r.get("value", "")) or
                  "security" in _norm(r.get("key", ""))
                  for r in store.all("deleted"))
    still = any("security-team" in _norm(r.get("value", ""))
                for r in store.all("current"))
    _fb(deleted and not still, "revocation applied (security-team deleted, "
                               "nothing current still mentions it)")
    seen = {op["op"] for op in store.operations}
    _fb({"ADD", "UPDATE", "DELETE", "NOOP"} <= seen,
        f"verdicts seen: {', '.join(sorted(seen)) or 'none'} "
        "(all four occur in this transcript)")
    _fb(None if not store.leaked_secrets(FORBIDDEN_IN_MEMORY) else False,
        "grep \"sk-\" runs/final_memory.jsonl must print nothing"
        if not store.leaked_secrets(FORBIDDEN_IN_MEMORY)
        else "A SECRET IS IN THE FINAL STORE")


def _render_ladder(assembled) -> None:
    """The rungs: red ✗ = did not fit, climb; green ✓ = landed."""
    print(f"  {DIM}the ladder - cheap before expensive, lossless before lossy:{RESET}")
    for line in assembled.ladder:
        text = " ".join(str(line).split())
        if text.endswith("OK"):
            print(f"    {GREEN}{BOLD}✓ {text}   <- landed here{RESET}")
        else:
            print(f"    {RED}✗ {text}   -> does not fit, climb{RESET}")


def _feedback4(assembled, budget: int) -> None:

    print(f"\n{BOLD}  feedback (TODO 4){RESET}")
    _fb(assembled.tokens <= budget,
        f"fits the budget ({assembled.tokens:,}t <= {budget:,}t)")
    ladder = assembled.ladder
    trim_at = next((i for i, l in enumerate(ladder) if "trim" in l.lower()), None)
    compact_at = next((i for i, l in enumerate(ladder) if "compact" in l.lower()), None)
    _fb(trim_at is not None and (compact_at is None or trim_at < compact_at),
        "L1 (trim, free) was attempted before L2 (compact, one API call)")
    _fb(any(FINAL_INSTRUCTION in str(m.get("content", "")) for m in assembled.messages),
        "the user's final instruction survives verbatim in the tail")


# ---------------------------------------------------------------- the steps

def step1(policy, client) -> list:
    """Seed the initial store, then TODO 1: transcript -> candidates."""
    # A fresh lineage: stale files from an earlier run must not masquerade
    # as this run's output.
    for name in LINEAGE:
        (RUNS_ROOT / name).unlink(missing_ok=True)

    store = MemoryStore.load(RUNS_ROOT, INITIAL_FILE)
    for record in SEED_MEMORY:
        store.add(dict(record))
    store.operations.clear()  # seeding is scaffolding, not part of the run
    store.save()
    print(f"{DIM}seed store: " + " | ".join(
        f'{r["key"]}={r["value"]}' for r in store.all()) + RESET)
    print(f"{DIM}  saved -> runs/{INITIAL_FILE}{RESET}")

    _banner("STEP 1", "write_memory (extract)")
    candidates = policy.write_memory(client, TRANSCRIPT, TRANSCRIPT_SESSION_NO)
    for record in candidates:
        print(f"  · {json.dumps(record, ensure_ascii=False)}")
    if not candidates:
        print("  (no candidates extracted)")
    _save(STEP_FILES[1], candidates)
    _feedback1(candidates)
    return candidates


def step2(policy, candidates=None) -> tuple[list, list]:
    """TODO 2: candidates -> accepted + rejected. No API call, on purpose."""
    if candidates is None:
        candidates = _require(STEP_FILES[1], "--step 1")
    store = MemoryStore.load(RUNS_ROOT, INITIAL_FILE)  # reference only

    _banner("STEP 2", "validate_record (the write gate)")
    accepted, rejected = [], []
    for record in candidates:
        ok, reason = policy.validate_record(record, store)
        if ok:
            accepted.append(record)
            print(f"  {GREEN}✓ pass{RESET}   {json.dumps(record, ensure_ascii=False)}")
        else:
            rejected.append({"record": record, "reason": reason})
            print(f"  {RED}✗ reject{RESET} {json.dumps(record, ensure_ascii=False)}"
                  f"  {RED}({reason}){RESET}")
    _save(STEP_FILES[2], {"accepted": accepted, "rejected": rejected})
    _feedback2(accepted, rejected)
    return accepted, rejected


def step3(policy, client, accepted=None, rejected=None) -> MemoryStore:
    """TODO 3: accepted -> ADD/UPDATE/DELETE/NOOP against the seed store."""
    if accepted is None:
        gate = _require(STEP_FILES[2], "--step 2")
        accepted, rejected = gate["accepted"], gate["rejected"]

    initial = MemoryStore.load(RUNS_ROOT, INITIAL_FILE)
    if not initial.records:
        sys.exit(f"runs/{INITIAL_FILE} is empty - run --step 1 first.")
    store = MemoryStore(root=RUNS_ROOT, relpath=FINAL_FILE)
    store.records = [dict(r) for r in initial.records]
    store.rejections = list(rejected or [])

    _banner("STEP 3", "reconcile (ADD / UPDATE / DELETE / NOOP)")
    policy.reconcile(client, store, accepted, TRANSCRIPT, TRANSCRIPT_SESSION_NO)
    store.save()
    for op in store.operations:
        print(f"  · {json.dumps(op, ensure_ascii=False)}")
    print()
    print(store.report(TRANSCRIPT_SESSION_NO))
    _save(STEP_FILES[3], {"operations": store.operations,
                          "store_after": store.all("*")})
    print(f"{DIM}  saved -> runs/{FINAL_FILE}{RESET}")
    _feedback3(store)
    return store


def step4(policy, client, budget: int, store=None, candidates=None) -> None:
    """TODO 4: assemble under the budget, then the 20-point report card."""
    if candidates is None:
        candidates = _require(STEP_FILES[1], "--step 1")
    if store is None:
        store = MemoryStore.load(RUNS_ROOT, FINAL_FILE)
        if not store.records:
            sys.exit(f"runs/{FINAL_FILE} not found - run --step 3 first.")
        # Restore what grading needs from the earlier steps' files.
        gate = _require(STEP_FILES[2], "--step 2")
        store.rejections = list(gate["rejected"])
        ops = _require(STEP_FILES[3], "--step 3")
        store.operations = list(ops["operations"])

    _banner("STEP 4", f"build_context (budget {budget:,}t)")
    print(f"{DIM}  task: fit the whole transcript + the store into {budget:,}t "
          f"for the next model call (estimator {estimator_name()}){RESET}")
    history = [{"role": m["role"], "content": m["content"]} for m in TRANSCRIPT]
    assembled = None
    try:
        assembled = policy.build_context(client, PIPELINE_SYSTEM, store, history, budget)
        _render_ladder(assembled)
        _feedback4(assembled, budget)
    except ContextOverflow as exc:
        print(f"  {RED}{BOLD}CONTEXT OVERFLOW ▸ {exc}{RESET}")
        print(f"\n{BOLD}  feedback (TODO 4){RESET}")
        _fb(False, "nothing fits the budget - the ladder must degrade "
                   "step by step, not give up")

    grade = grade_pipeline(store, candidates, assembled, budget)
    print(f"\n{'─' * 72}")
    print(f" 🏆 pipeline   {verdict(grade.passed, grade.score, grade.total)}")
    print(f"{'─' * 72}")
    mark, colr = ("✓", GREEN) if grade.passed else ("✗", RED)
    for item in grade.feedback:
        print(f" {colr}{mark} {item}{RESET}")
    api = getattr(client, "log", None)
    if api is not None:
        print(f"\n{DIM} api: {api.summary()}{RESET}")
    print(f"{DIM} store: runs/{FINAL_FILE}  (grep \"sk-\" it - must print nothing){RESET}")


# ══════════════════════════════════════════════════════════════════════════
# ── section: part A flows — the tools / memory run flows and the comparison table
# ══════════════════════════════════════════════════════════════════════════

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


def make_client():
    return ZhipuClient.from_env()


def make_memory_policy(implementation: str, model: str):
    if implementation == "starter":
        # The class the notebook binds your answers onto - "starter" works
        # once the TODO cells have run in this kernel.
        return MemoryPolicy(model=model)
    # Lazy import: memory_agent.py imports back from this module.
    from memory_agent import MemoryPolicy as ReferencePolicy

    return ReferencePolicy(model=model)


def run_one(mode: str, args, client) -> dict:
    # Lazy import: memory_agent.py imports back from this module.
    from memory_agent import ToolsPolicy

    label = mode
    run_banner(label, 0)

    # Only the memory run keeps a store file; the tools run holds an empty
    # in-memory store - that is its point.
    if mode == "memory":
        store = MemoryStore.load(RUNS_ROOT, "memory.jsonl")
        policy = make_memory_policy(args.implementation, args.model)
    else:
        store = MemoryStore()
        policy = ToolsPolicy()
    if args.session is None:
        store.reset()

    registry = build_agent_registry(WORKSPACE_ROOT)
    system_prompt = AGENT_SYSTEM_TEMPLATE.format(tools=registry.describe())

    try:
        result = run_sessions(
            client=client,
            policy=policy,
            store=store,
            sessions=SESSIONS,
            system_prompt=system_prompt,
            registry=registry,
            verifier=finish_verifier,
            model=args.model,
            only_session=args.session,
            verbose=not args.quiet,
            max_steps=args.max_steps,
            answer_keys=set(EXPECTED_ANSWER),
            on_session_start=lambda _n: reset_workspace(),
        )
    except NotImplementedError as exc:
        print(f"\nStarter is incomplete: {exc}")
        return {"mode": mode, "error": str(exc)}

    grade = grade_demo(result.answer, registry)
    peak = max((t.context_tokens for t in result.turns), default=0)
    api = getattr(client, "log", None)

    partial = args.session == 1  # the deliverable is asked for in session 2
    summary_card(
        label=label, budget=0,
        passed=grade.passed, score=grade.score, total=grade.total,
        feedback=grade.feedback,
        answer=result.answer, stopped=result.stopped_reason, peak=peak,
        compactions=0, rung=0,
        mem=(len(store.all("current")), len(store.all("superseded")),
             len(store.all("deleted"))),
        api=api.summary() if api is not None else "",
        drift=result.drift.summary(),
        partial_note=("session 1 only — the deliverable is requested in "
                      "session 2; look at runs/memory.jsonl instead"
                      if partial else None),
    )

    return {
        "mode": mode,
        "passed": grade.passed,
        "score": grade.score,
        "total": grade.total,
        "answer": result.answer,
        "stopped_reason": result.stopped_reason,
        "grade": asdict(grade),
        "peak_context_tokens": peak,
        "api_calls": api.total_calls if api else 0,
        "api_prompt_tokens": api.total_prompt_tokens if api else 0,
        "turns": [asdict(t) for t in result.turns],
        "tool_calls": registry.history,
        "memory": store.all("*"),
        "rejections": store.rejections,
    }


def print_comparison(runs: list[dict]) -> None:
    print(f"\n{'=' * 72}\nCOMPARISON   (estimator {estimator_name()})\n{'=' * 72}")
    header = f"{'run':<10}{'result':>10}{'answer':>34}{'api calls':>12}"
    print(header)
    print("-" * len(header))
    for data in runs:
        if "error" in data:
            print(f"{data['mode']:<10}{'ERROR':>10}")
            continue
        shown = json.dumps(data["answer"], ensure_ascii=False)
        if len(shown) > 32:
            shown = shown[:29] + "..."
        print(
            f"{data['mode']:<10}"
            f"{'PASS' if data['passed'] else 'FAIL':>10}"
            f"{shown:>34}"
            f"{data['api_calls']:>12}"
        )

    by_mode = {d["mode"]: d for d in runs if "error" not in d}
    tools, memory = by_mode.get("tools"), by_mode.get("memory")
    if tools and memory:
        print(
            "\nSame tools, same loop, same model, same grader. The only line of "
            "code that differs is what happens when a session ends: the tools "
            "run keeps nothing, the memory run extracts two facts (~20 tokens) "
            "and session 2 starts with them in a [memory] block. Tools extend "
            "what an agent can DO; memory extends what it can KEEP."
        )
