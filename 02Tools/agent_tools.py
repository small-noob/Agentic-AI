"""Reference workspace tools, all routed through the path sandbox.

``build_workspace_tools`` is deliberately generic: point it at any directory and
you get a sandboxed file toolset back. Chapter 3 reuses it for a memory
directory, chapter 4 for a scratch directory.
"""

from __future__ import annotations

from pathlib import Path

from calculator import normalize_expression, safe_calculate
from registry import ToolError, ToolRegistry
from sandbox import SandboxError, relative_to_root, resolve_safe_path

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
