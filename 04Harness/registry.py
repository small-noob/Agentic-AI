"""A tiny tool registry: decorate a function, get a schema the model can read.

Lesson 1 hard-coded one tool into the loop. Once an agent needs several tools it
needs three things the loop should not know about individually:

1. a machine-readable description of each tool (so the model can pick one),
2. argument validation (so a weak model's bad call fails loudly, not silently),
3. an auditable call history (so a grader can check *how* the answer was found).

Later chapters import this module directly and register their own tools.
"""

from __future__ import annotations

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
