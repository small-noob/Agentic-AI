"""The graders themselves, pinned.

The most important assertion in this file: finish_verifier NEVER checks answer
values. Its errors go back to the model as Observations, so a verifier that
compared against the expected answer would quietly hand the model the answer.
It checks the agent's own tool history instead - chapter 2's boundary, kept.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grader import finish_verifier, grade_demo, grade_pipeline  # noqa: E402
from memory_store import MemoryStore  # noqa: E402
from react_loop import Assembled  # noqa: E402
from sessions import (  # noqa: E402
    EXPECTED_EXTRACTED,
    SEED_MEMORY,
    WORKSPACE_ROOT,
    reset_workspace,
)
from tools import build_agent_registry  # noqa: E402


def registry_with(*calls):
    reset_workspace()
    registry = build_agent_registry(WORKSPACE_ROOT)
    for name, arguments in calls:
        registry.call(name, arguments)
    return registry


READ_AND_COMPUTE = (
    ("read_file", {"path": "incident_0812.txt"}),
    ("calculate", {"expression": "7 * 200"}),
)


class TestDemoGrading(unittest.TestCase):
    def test_a_complete_run_passes(self):
        grade = grade_demo({"records": "7", "total_fine": "1400"},
                           registry_with(*READ_AND_COMPUTE))
        self.assertTrue(grade.passed, grade.feedback)

    def test_a_missing_answer_fails(self):
        grade = grade_demo(None, registry_with(*READ_AND_COMPUTE))
        self.assertFalse(grade.passed)

    def test_a_wrong_total_fails(self):
        grade = grade_demo({"records": "7", "total_fine": "1000"},
                           registry_with(*READ_AND_COMPUTE))
        self.assertFalse(grade.passed)

    def test_reading_the_wrong_incident_fails(self):
        registry = registry_with(
            ("read_file", {"path": "incident_0819.txt"}),
            ("calculate", {"expression": "7 * 200"}),
        )
        grade = grade_demo({"records": "7", "total_fine": "1400"}, registry)
        self.assertFalse(grade.passed)


class TestFinishVerifier(unittest.TestCase):
    def test_blocks_an_uncomputed_total(self):
        registry = registry_with(("read_file", {"path": "incident_0812.txt"}))
        errors = finish_verifier({"records": "7", "total_fine": "1400"}, registry)
        self.assertTrue(errors)

    def test_blocks_a_total_the_calculator_never_returned(self):
        registry = registry_with(
            ("read_file", {"path": "incident_0812.txt"}),
            ("calculate", {"expression": "5 * 200"}),  # produced 1000, not 1400
        )
        errors = finish_verifier({"records": "7", "total_fine": "1400"}, registry)
        self.assertTrue(errors)

    def test_blocks_an_unread_incident_file(self):
        registry = registry_with(("calculate", {"expression": "7 * 200"}))
        errors = finish_verifier({"records": "7", "total_fine": "1400"}, registry)
        self.assertTrue(errors)

    def test_never_checks_the_answer_value(self):
        """A WRONG answer sails through as long as the process is real.

        7 records were never read here - the agent computed 5 * 200 after
        reading the wrong file, and submits 1000. The verifier lets it pass:
        catching the wrong VALUE is grading's job, and grading's errors are
        never shown to the model.
        """
        registry = registry_with(
            ("read_file", {"path": "incident_0805.txt"}),
            ("calculate", {"expression": "5 * 200"}),
        )
        errors = finish_verifier({"records": "5", "total_fine": "1000"}, registry)
        self.assertEqual(errors, [])


def full_marks_store():
    store = MemoryStore()
    for record in SEED_MEMORY:
        store.add(dict(record))
    store.operations.clear()
    store.add({"key": "log_file", "value": "logs/access_2026-09.csv",
               "source": "session1", "session": 1})
    store.add({"key": "audit_day", "value": "1", "source": "session1", "session": 1})
    store.supersede("fine_per_violation",
                    {"key": "fine_per_violation", "value": "250",
                     "source": "session1", "session": 1})
    store.soft_delete("report_recipient", source="session1")
    store.noop("incident_file")
    store.log_rejection({"key": "zai_api_key", "value": "sk-xxxx"}, "secret")
    return store


def full_marks_assembly():
    from grader import FINAL_INSTRUCTION
    return Assembled(
        messages=[{"role": "user", "content": FINAL_INSTRUCTION}],
        tokens=500,
        ladder=["L0  raw assembly 795t OVER",
                "L1  trimmed oversized (-190t) 605t OVER",
                "L2  compact 0..N-4 (14 turns -> 60t) 500t OK"],
    )


CANDIDATES = [{"key": key, "value": value}
              for key, value in EXPECTED_EXTRACTED.items()]

# What the mock extractor also offers: the three candidates the gate must catch.
BAD_CANDIDATES = CANDIDATES + [
    {"key": "zai_api_key", "value": "sk-proj-3f9Qd7LmXb2vNp8KwRt5Yh1Zc4Ja6Ge0Su"},
    {"key": "audit_scope", "value": "the ServerRoom and the Lab"},
    {"key": "note"},
]


class TestPipelineGrading(unittest.TestCase):
    def test_a_complete_pipeline_scores_twenty(self):
        grade = grade_pipeline(full_marks_store(), CANDIDATES,
                               full_marks_assembly(), 600)
        self.assertTrue(grade.passed, grade.feedback)
        self.assertEqual((grade.score, grade.total), (20, 20))

    def test_the_write_gate_item_is_all_or_nothing(self):
        store = full_marks_store()
        store.add({"key": "leaked", "value": "sk-proj-3f9Qd7LmXb2vNp8KwRt5Yh1Zc4Ja6Ge0Su",
                   "source": "session1", "session": 1})
        grade = grade_pipeline(store, CANDIDATES, full_marks_assembly(), 600)
        self.assertEqual(grade.score, 14, "one leak must cost the whole 6-point item")

    def test_a_gate_that_never_fired_earns_nothing(self):
        # Extraction OFFERED bad candidates and none were rejected: gate is off.
        store = full_marks_store()
        store.rejections.clear()
        grade = grade_pipeline(store, BAD_CANDIDATES, full_marks_assembly(), 600)
        self.assertEqual(grade.score, 14)

    def test_an_idle_gate_on_a_clean_run_is_not_a_failure(self):
        # A live model sometimes extracts cleanly; with nothing to reject,
        # an empty rejection log costs nothing. (The mock channel always
        # offers bad candidates, so the gate is still exercised offline.)
        store = full_marks_store()
        store.rejections.clear()
        grade = grade_pipeline(store, CANDIDATES, full_marks_assembly(), 600)
        self.assertEqual(grade.score, 20)

    def test_update_without_an_audit_trail_loses_two(self):
        store = full_marks_store()
        for record in store.records:
            if record["status"] == "superseded":
                record["status"] = "deleted"  # break the trail
        grade = grade_pipeline(store, CANDIDATES, full_marks_assembly(), 600)
        self.assertEqual(grade.score, 18)

    def test_compact_before_trim_loses_the_ordering_point(self):
        assembled = full_marks_assembly()
        assembled.ladder = ["L0  raw assembly 795t OVER",
                            "L2  compact 0..N-4 (14 turns -> 60t) 500t OK"]
        grade = grade_pipeline(full_marks_store(), CANDIDATES, assembled, 600)
        self.assertEqual(grade.score, 19)

    def test_a_blown_budget_loses_two(self):
        assembled = full_marks_assembly()
        assembled.tokens = 700
        grade = grade_pipeline(full_marks_store(), CANDIDATES, assembled, 600)
        self.assertEqual(grade.score, 18)


if __name__ == "__main__":
    unittest.main()
