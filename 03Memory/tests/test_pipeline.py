"""Part B end to end, offline: the reference pipeline over the transcript.

This is the 20/20 the students are aiming at, pinned as a test. The mock
extractor deliberately produces GLM-4-Flash's real mistakes (it transcribes
the credential, packs two facts into one record, emits a record with no
value), so the gate's rejections here are the same ones a live run shows.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grader import grade_pipeline  # noqa: E402
from memory_agent import MemoryPolicy  # noqa: E402
from memory_store import MemoryStore  # noqa: E402
from mock_client import MockClient  # noqa: E402
from sessions import (  # noqa: E402
    EXPECTED_EXTRACTED,
    FORBIDDEN_IN_MEMORY,
    PIPELINE_BUDGET,
    PIPELINE_SYSTEM,
    SEED_MEMORY,
    TRANSCRIPT,
    TRANSCRIPT_SESSION_NO,
)


class TestReferencePipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MockClient()
        cls.policy = MemoryPolicy()
        cls.store = MemoryStore()
        for record in SEED_MEMORY:
            cls.store.add(dict(record))
        cls.store.operations.clear()

        cls.candidates = cls.policy.write_memory(
            cls.client, TRANSCRIPT, TRANSCRIPT_SESSION_NO
        )
        cls.accepted = []
        for record in cls.candidates:
            ok, reason = cls.policy.validate_record(record, cls.store)
            if ok:
                cls.accepted.append(record)
            else:
                cls.store.log_rejection(record, reason)
        cls.policy.reconcile(
            cls.client, cls.store, cls.accepted, TRANSCRIPT, TRANSCRIPT_SESSION_NO
        )
        history = [{"role": m["role"], "content": m["content"]} for m in TRANSCRIPT]
        cls.assembled = cls.policy.build_context(
            cls.client, PIPELINE_SYSTEM, cls.store, history, PIPELINE_BUDGET
        )

    # ---- TODO 1 ---------------------------------------------------------
    def test_extraction_surfaces_every_expected_fact(self):
        keys = {r.get("key") for r in self.candidates}
        for key in EXPECTED_EXTRACTED:
            self.assertIn(key, keys)

    def test_extraction_reads_user_turns_only(self):
        keys = {r.get("key") for r in self.candidates}
        self.assertNotIn("ten_record_total", keys,
                         "the assistant's wrong arithmetic was extracted")

    # ---- TODO 2 ---------------------------------------------------------
    def test_the_gate_rejected_the_three_bad_candidates(self):
        reasons = {item["reason"] for item in self.store.rejections}
        self.assertIn("secret", reasons)
        self.assertIn("two facts in one record", reasons)
        self.assertIn("missing value", reasons)

    def test_no_secret_reached_the_store(self):
        self.assertEqual(self.store.leaked_secrets(FORBIDDEN_IN_MEMORY), [])

    # ---- TODO 3 ---------------------------------------------------------
    def test_update_kept_the_audit_trail(self):
        self.assertEqual(self.store.get("fine_per_violation")["value"], "250")
        olds = [r for r in self.store.all("superseded")
                if r["key"] == "fine_per_violation" and r["value"] == "200"]
        self.assertTrue(olds)

    def test_revocation_was_applied(self):
        self.assertIsNone(self.store.get("report_recipient"))
        deleted = [r for r in self.store.all("deleted")
                   if r["key"] == "report_recipient"]
        self.assertTrue(deleted)

    def test_all_four_verdicts_occurred(self):
        ops = {op["op"] for op in self.store.operations}
        self.assertEqual(ops, {"ADD", "UPDATE", "DELETE", "NOOP"})

    # ---- TODO 4 ---------------------------------------------------------
    def test_the_assembly_fits_the_budget(self):
        self.assertLessEqual(self.assembled.tokens, PIPELINE_BUDGET)

    def test_the_ladder_climbed_in_order(self):
        rungs = [line.split()[0] for line in self.assembled.ladder]
        self.assertEqual(rungs[0], "L0")
        self.assertIn("L1", rungs)

    def test_the_final_instruction_survives_verbatim(self):
        from grader import FINAL_INSTRUCTION
        self.assertTrue(any(FINAL_INSTRUCTION in str(m.get("content", ""))
                            for m in self.assembled.messages))

    # ---- the report card --------------------------------------------------
    def test_scores_full_marks(self):
        grade = grade_pipeline(self.store, self.candidates, self.assembled,
                               PIPELINE_BUDGET)
        self.assertTrue(grade.passed, grade.feedback)
        self.assertEqual(grade.score, 20)


if __name__ == "__main__":
    unittest.main()
