"""Skills: procedural knowledge packaged as a folder with a SKILL.md.

A tool is one atomic operation the runtime performs. A skill is a *procedure* —
several steps, edge cases, and output conventions — written once and reused.

The point of the format is progressive disclosure: only ``name`` and
``description`` sit in the system prompt (a few dozen tokens per skill), and the
model pulls the full body with ``load_skill`` when it judges the skill relevant.
A hundred skills therefore cost roughly what one instruction paragraph costs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from registry import ToolError, ToolRegistry

MAX_DESCRIPTION_CHARS = 400
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class SkillError(Exception):
    """A SKILL.md is missing, malformed, or missing required metadata."""


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path

    def index_line(self) -> str:
        return f"- {self.name}: {self.description}"


def parse_skill_md(text: str, source: str = "<string>") -> tuple[dict[str, str], str]:
    """Split YAML-style frontmatter from the markdown body.

    Only flat ``key: value`` pairs are supported, which keeps the loader free of
    a YAML dependency and keeps the format obvious to students.
    """

    match = FRONTMATTER_RE.match(text)
    if not match:
        raise SkillError(f"{source}: missing '---' frontmatter block at the top of the file")

    metadata: dict[str, str] = {}
    for line_number, raw in enumerate(match.group(1).splitlines(), start=2):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise SkillError(f"{source}: line {line_number} is not a 'key: value' pair")
        key, _, value = line.partition(":")
        metadata[key.strip()] = value.strip().strip("'\"")

    return metadata, match.group(2).strip()


def load_skill_file(skill_md: Path) -> Skill:
    metadata, body = parse_skill_md(skill_md.read_text(encoding="utf-8"), source=str(skill_md))

    for required in ("name", "description"):
        if not metadata.get(required):
            raise SkillError(f"{skill_md}: frontmatter must define a non-empty '{required}'")
    if len(metadata["description"]) > MAX_DESCRIPTION_CHARS:
        raise SkillError(
            f"{skill_md}: description must stay under {MAX_DESCRIPTION_CHARS} characters — "
            "it lives in every system prompt, so it pays for itself only if it is short"
        )
    if not body:
        raise SkillError(f"{skill_md}: the body below the frontmatter is empty")

    return Skill(metadata["name"], metadata["description"], body, skill_md)


def discover_skills(skills_dir: str | Path) -> dict[str, Skill]:
    """Load every ``<skills_dir>/<folder>/SKILL.md``."""

    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return {}
    skills: dict[str, Skill] = {}
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        skill = load_skill_file(skill_md)
        skills[skill.name] = skill
    return skills


def skill_index(skills: dict[str, Skill]) -> str:
    if not skills:
        return "(no skills available)"
    return "\n".join(skills[name].index_line() for name in sorted(skills))


def register_skill_tool(registry: ToolRegistry, skills: dict[str, Skill]) -> ToolRegistry:
    """Expose ``load_skill`` so the model can pull a full procedure on demand."""

    @registry.tool(
        "Load the full step-by-step procedure for one of the available skills.",
        name="Skill name exactly as listed in the skills catalogue.",
    )
    def load_skill(name: str) -> str:
        skill = skills.get(name.strip())
        if skill is None:
            available = ", ".join(sorted(skills)) or "(none)"
            raise ToolError(f"Unknown skill '{name}'. Available skills: {available}")
        return f"# Skill: {skill.name}\n\n{skill.body}"

    return registry
