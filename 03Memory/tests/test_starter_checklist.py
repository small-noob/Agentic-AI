"""The checklist, as tests. It starts red; all green means the TODOs are done.

Chapter 2 did the same thing (its suite fails on the untouched starter in
exactly the places students have work to do), so red-until-done is expected:
run the suite before writing anything and read the failures as your task list.

Each test drives one TODO through the offline mock, so a green here means the
TODO not only exists but produces something the pipeline can use - still
without spending a single API token.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_starter import MemoryPolicy as StarterPolicy  # noqa: E402
from memory_store import MemoryStore  # noqa: E402
from mock_client import SECRET_IN_PASTE, MockClient  # noqa: E402
from react_loop import Assembled  # noqa: E402
from sessions import SEED_MEMORY, TRANSCRIPT  # noqa: E402


class StarterChecklistTests(unittest.TestCase):
    """One test per TODO. A NotImplementedError reads as 'not started'."""

    def setUp(self):
        self.policy = StarterPolicy()
        self.client = MockClient()
        self.store = MemoryStore()

    def test_todo_1_write_memory_extracts_records(self):
        try:
            records = self.policy.write_memory(self.client, TRANSCRIPT, 1)
        except NotImplementedError:
            self.fail("TODO 1 (write_memory) is not implemented yet")
        self.assertTrue(records, "write_memory returned no candidate records")
        for record in records:
            self.assertIsInstance(record, dict)
        keys = {r.get("key") for r in records}
        self.assertIn("fine_per_violation", keys,
                      "the extraction prompt is not surfacing the transcript's facts")
        self.assertIn("log_file", keys,
                      "the extraction prompt is not surfacing the transcript's facts")
        self.assertNotIn(
            "ten_record_total", keys,
            "the assistant's wrong arithmetic was extracted - flatten USER "
            "turns only, or the pipeline poisons itself",
        )

    def test_todo_2_validate_record_is_a_deterministic_gate(self):
        try:
            ok, _ = self.policy.validate_record(
                {"key": "fine_per_violation", "value": "250"}, self.store
            )
        except NotImplementedError:
            self.fail("TODO 2 (validate_record) is not implemented yet")
        self.assertTrue(ok, "a clean record must be admitted")
        bad, reason = self.policy.validate_record(
            {"key": "zai_api_key", "value": SECRET_IN_PASTE}, self.store
        )
        self.assertFalse(bad, "the pasted credential must be rejected")
        self.assertTrue(reason, "a rejection needs a printable reason")

    def test_todo_3_reconcile_applies_all_four_verdicts(self):
        for record in SEED_MEMORY:
            self.store.add(dict(record))
        self.store.operations.clear()
        candidates = [
            {"key": "fine_per_violation", "value": "250", "source": "session1", "session": 1},
            {"key": "incident_file", "value": "incident_0812.txt", "source": "session1", "session": 1},
            {"key": "log_file", "value": "logs/access_2026-09.csv", "source": "session1", "session": 1},
        ]
        try:
            self.policy.reconcile(self.client, self.store, candidates, TRANSCRIPT, 1)
        except NotImplementedError:
            self.fail("TODO 3 (reconcile) is not implemented yet")
        self.assertEqual(self.store.get("fine_per_violation")["value"], "250",
                         "UPDATE did not apply")
        self.assertTrue(self.store.all("superseded"), "UPDATE must keep the audit trail")
        self.assertIsNone(self.store.get("report_recipient"),
                          "the revocation pass never deleted report_recipient")
        ops = {op["op"] for op in self.store.operations}
        self.assertIn("NOOP", ops, "an exact duplicate should be a NOOP, not a write")
        self.assertIn("ADD", ops, "new facts should be ADDed")

    def test_todo_4_build_context_fits_the_budget(self):
        history = [{"role": m["role"], "content": m["content"]} for m in TRANSCRIPT]
        try:
            assembled = self.policy.build_context(
                self.client, "system prompt", self.store, history, budget=700
            )
        except NotImplementedError:
            self.fail("TODO 4 (build_context) is not implemented yet")
        self.assertIsInstance(assembled, Assembled)
        self.assertLessEqual(assembled.tokens, 700,
                             "the assembled context is over the budget it was given")
        self.assertTrue(assembled.ladder, "record each rung so the degradation is visible")


if __name__ == "__main__":
    unittest.main()
