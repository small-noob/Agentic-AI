import unittest

from grader import extract_json_answer, grade_answer


class GraderTests(unittest.TestCase):
    def test_extracts_json_from_model_text(self):
        answer = extract_json_answer('Final: {"answer":"156003"}')
        self.assertEqual(answer, {"answer": "156003"})

    def test_wrong_answer_fails(self):
        self.assertFalse(grade_answer({"answer": "156004"}).passed)

    def test_extracts_weak_model_near_json(self):
        self.assertEqual(
            extract_json_answer("answer=156003"),
            {"answer": "156003"},
        )


if __name__ == "__main__":
    unittest.main()
