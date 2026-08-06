import unittest

from grader import grade_react_run
from mock_client import ScriptedMockClient
from react_agent import ReactAgent, parse_action
from task import TASK_PROMPT
from tools import ToolEnvironment


class ReActTests(unittest.TestCase):
    def test_parser_accepts_calculate_action(self):
        action = parse_action("Thought: Need the seed.\nAction: Calculate[pow(2,10,100)]")
        self.assertEqual(action.name, "Calculate")
        self.assertEqual(action.argument, "pow(2,10,100)")

    def test_offline_react_passes_answer_and_process_grade(self):
        tools = ToolEnvironment()
        result = ReactAgent(ScriptedMockClient(), tools, max_steps=6).run(TASK_PROMPT)
        grade = grade_react_run(result.answer, tools.history)
        self.assertTrue(grade.passed, grade.feedback)
        self.assertEqual(grade.score, 12)
        self.assertEqual(len(result.steps), 3)

    def test_finish_before_second_calculation_is_blocked(self):
        class EarlyFinishClient:
            def __init__(self):
                self.index = 0
                self.responses = [
                    "Thought: Get seed.\nAction: Calculate[pow(20250807,123457,1000000)]",
                    'Thought: Guess.\nAction: Finish[{"answer":"156003"}]',
                    "Thought: S is odd; calculate odd branch.\nAction: Calculate[(730807*2025+271828)%1000000]",
                    'Thought: Finish.\nAction: Finish[{"answer":"156003"}]',
                ]

            def chat(self, messages, model, temperature=0.2, max_tokens=900):
                response = self.responses[self.index]
                self.index += 1
                return response

        tools = ToolEnvironment()
        result = ReactAgent(EarlyFinishClient(), tools, max_steps=6).run(TASK_PROMPT)
        self.assertEqual(result.answer, {"answer": "156003"})
        self.assertIn("Finish blocked", result.steps[1].observation)


if __name__ == "__main__":
    unittest.main()
