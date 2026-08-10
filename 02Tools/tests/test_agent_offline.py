import shutil
import tempfile
import unittest
from pathlib import Path

import sandbox
from agent import ToolAgent, parse_action
from agent_tools import build_workspace_tools
from grader import grade_answer, grade_process, grade_run
from main import make_verifier
from mock_client import ScriptedMockClient
from skill_loader import discover_skills, register_skill_tool, skill_index
from task import SKILLS_DIR, TASK_PROMPT, WORKSPACE_ROOT


class ParserTests(unittest.TestCase):
    def test_parses_two_line_action(self):
        action = parse_action(
            'Thought: read it.\nAction: read_file\nAction Input: {"path": "policy.json"}',
            build_workspace_tools(WORKSPACE_ROOT),
        )
        self.assertEqual(action.name, "read_file")
        self.assertEqual(action.arguments, {"path": "policy.json"})

    def test_parses_inline_arguments(self):
        action = parse_action(
            'Action: read_file {"path": "policy.json"}',
            build_workspace_tools(WORKSPACE_ROOT),
        )
        self.assertEqual(action.arguments, {"path": "policy.json"})

    def test_bare_value_is_accepted_for_single_argument_tools(self):
        action = parse_action(
            "Action: read_file\nAction Input: policy.json",
            build_workspace_tools(WORKSPACE_ROOT),
        )
        self.assertEqual(action.arguments, {"path": "policy.json"})

    def test_prose_without_an_action_returns_none(self):
        self.assertIsNone(parse_action("I think the answer is B1005.", build_workspace_tools(WORKSPACE_ROOT)))


class OfflineRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        shutil.copytree(WORKSPACE_ROOT, self.root)
        self.addCleanup(self.tmp.cleanup)

    def run_agent(self, use_skills: bool):
        registry = build_workspace_tools(self.root)
        index = ""
        if use_skills:
            skills = discover_skills(SKILLS_DIR)
            register_skill_tool(registry, skills)
            index = skill_index(skills)
        agent = ToolAgent(
            ScriptedMockClient(),
            registry,
            verifier=make_verifier(require_skill=use_skills),
            skill_index=index,
            max_steps=12,
        )
        return agent.run(TASK_PROMPT), registry

    def test_skill_run_scores_full_marks(self):
        result, registry = self.run_agent(use_skills=True)
        grade = grade_run(result.answer, registry, sandbox.resolve_safe_path, require_skill=True)
        self.assertTrue(grade.passed, grade.feedback)
        self.assertEqual(grade.score, 20)
        self.assertTrue(registry.called("load_skill"))

    def test_noskill_run_fails_on_answer_and_process(self):
        result, registry = self.run_agent(use_skills=False)
        self.assertEqual(result.answer["violations"], 7)
        self.assertFalse(grade_answer(result.answer).passed)
        self.assertFalse(grade_process(registry, require_skill=False).passed)

    def test_verifier_blocks_a_premature_finish(self):
        result, _ = self.run_agent(use_skills=False)
        blocked = [step for step in result.steps if step.observation and "blocked by verifier" in step.observation]
        self.assertTrue(blocked, "the guessing finish should have been rejected")

    def test_report_is_written_inside_the_workspace(self):
        self.run_agent(use_skills=True)
        self.assertIn("B1005", (self.root / "reports" / "audit.md").read_text())


if __name__ == "__main__":
    unittest.main()
