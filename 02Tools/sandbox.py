"""Path sandbox: every file tool must route through here.

Reference implementation. Students write their own version in
``starter_tools.py``; the red-team suite in ``tests/test_sandbox.py`` grades
both against the same ten attacks.
"""

from __future__ import annotations

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
