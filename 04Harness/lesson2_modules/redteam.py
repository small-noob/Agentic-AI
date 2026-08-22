"""Ten sandbox escape attempts. A path sandbox is only worth its name if it
blocks every one of them.

The suite builds its own throwaway workspace so it never depends on files the
students may have edited, and so it can plant symlinks that are awkward to keep
in git.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SECRET_MARKER = "SANDBOX_ESCAPE_MARKER"


@dataclass
class Attack:
    name: str
    path: str
    intent: str
    needs_link: str | None = None
    """The symlink trap this attack needs, if any.

    Creating a symlink on Windows requires Developer Mode or an elevated
    shell. Where it cannot be created the attack cannot be staged at all, so
    it is reported as skipped rather than silently counted as blocked.
    """


ATTACKS: list[Attack] = [
    Attack("parent_traversal", "../secrets.env", "step out of the workspace with .."),
    Attack("deep_traversal", "../../../../etc/passwd", "climb to a system file"),
    Attack("absolute_path", "/etc/passwd", "ignore the root entirely"),
    Attack("nested_traversal", "logs/../../secrets.env", "hide .. behind a real folder"),
    Attack("bare_parent", "..", "list the parent directory"),
    Attack("home_expansion", "~/.ssh/id_rsa", "lean on shell-style ~ expansion"),
    Attack("symlink_to_file", "escape_secrets", "follow a symlink to an outside file", needs_link="escape_secrets"),
    Attack("symlink_to_dir", "escape_dir/secrets.env", "follow a symlink to an outside folder", needs_link="escape_dir"),
    Attack("symlink_absolute", "escape_etc", "follow a symlink to an absolute path", needs_link="escape_etc"),
    Attack("write_outside", "../pwned.txt", "write above the workspace root"),
]


def build_attack_workspace(base: Path) -> Path:
    """Create ``base/outer/workspace`` plus the bait and the symlink traps."""

    outer = base / "outer"
    root = outer / "workspace"
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / "sample.csv").write_text("timestamp,badge_id\n", encoding="utf-8")
    (outer / "secrets.env").write_text(f"API_KEY={SECRET_MARKER}\n", encoding="utf-8")

    for link_name, target in (
        ("escape_secrets", outer / "secrets.env"),
        ("escape_dir", outer),
        ("escape_etc", Path("/etc")),
    ):
        link = root / link_name
        if link.is_symlink() or link.exists():
            link.unlink()
        try:
            link.symlink_to(target)
        except OSError:
            pass        # no symlink privilege; run_attacks reports these skipped

    return root


LEGITIMATE: list[tuple[str, str, bool]] = [
    ("workspace_root", ".", True),
    ("existing_file", "logs/sample.csv", True),
    ("new_file", "reports/audit.md", False),
]


def run_legitimate(resolve_fn: Callable[..., Path], root: Path) -> list[dict]:
    """A sandbox that refuses everything blocks every attack and is still broken.

    These three requests must succeed, otherwise the resolver is not a sandbox,
    it is an unconditional ``raise``.
    """

    root_resolved = Path(root).resolve()
    results = []
    for name, path, must_exist in LEGITIMATE:
        try:
            resolved = Path(resolve_fn(root_resolved, path, must_exist=must_exist)).resolve()
        except Exception as exc:
            results.append({"case": name, "allowed": False, "detail": f"{type(exc).__name__}: {exc}"})
            continue
        inside = resolved == root_resolved or root_resolved in resolved.parents
        results.append(
            {
                "case": name,
                "allowed": inside,
                "detail": str(resolved) if inside else f"resolved outside the root: {resolved}",
            }
        )
    return results


def run_attacks(resolve_fn: Callable[..., Path], root: Path) -> list[dict]:
    """Return one result row per attack.

    An attack counts as blocked when the resolver raises, or when it returns a
    path that still lives inside the root (some attacks are harmless if the
    resolver normalises them instead of rejecting them).
    """

    root_resolved = Path(root).resolve()
    results = []
    for attack in ATTACKS:
        if attack.needs_link and not (root_resolved / attack.needs_link).is_symlink():
            results.append({
                "attack": attack.name,
                "blocked": False,
                "skipped": True,
                "detail": "symlink trap could not be created on this platform",
            })
            continue
        try:
            resolved = Path(resolve_fn(root_resolved, attack.path)).resolve()
        except Exception as exc:
            results.append({"attack": attack.name, "blocked": True, "detail": f"{type(exc).__name__}: {exc}"})
            continue
        inside = resolved == root_resolved or root_resolved in resolved.parents
        results.append(
            {
                "attack": attack.name,
                "blocked": inside,
                "detail": "normalised inside the root" if inside else f"ESCAPED to {resolved}",
            }
        )
    return results
