import unittest

from registry import ToolRegistry
from skill_loader import (
    MAX_DESCRIPTION_CHARS,
    SkillError,
    discover_skills,
    parse_skill_md,
    register_skill_tool,
    skill_index,
)
from task import SKILLS_DIR

VALID = """---
name: demo
description: Does a demo thing. Use when demoing.
---

## Procedure

1. Do the thing.
"""


class SkillLoaderTests(unittest.TestCase):
    def test_parses_frontmatter_and_body(self):
        metadata, body = parse_skill_md(VALID)
        self.assertEqual(metadata["name"], "demo")
        self.assertTrue(body.startswith("## Procedure"))

    def test_missing_frontmatter_is_rejected(self):
        with self.assertRaises(SkillError):
            parse_skill_md("# Just a heading\n")

    def test_reference_skill_loads(self):
        skills = discover_skills(SKILLS_DIR)
        self.assertIn("audit_access_log", skills)
        skill = skills["audit_access_log"]
        self.assertLessEqual(len(skill.description), MAX_DESCRIPTION_CHARS)
        self.assertIn("policy.json", skill.body)

    def test_index_stays_far_smaller_than_the_body(self):
        skills = discover_skills(SKILLS_DIR)
        body_chars = sum(len(skill.body) for skill in skills.values())
        self.assertLess(len(skill_index(skills)) * 4, body_chars)

    def test_load_skill_tool_returns_the_body(self):
        registry = register_skill_tool(ToolRegistry(), discover_skills(SKILLS_DIR))
        output = registry.call("load_skill", {"name": "audit_access_log"})
        self.assertIn("Procedure", output)
        self.assertIn("Unknown skill", registry.call("load_skill", {"name": "nope"}))


if __name__ == "__main__":
    unittest.main()
