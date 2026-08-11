"""TODO 2 is the only TODO that is fully unit testable - that is the point of it.

A gate that calls the model cannot be tested like this, which is exactly why the
gate does not call the model. Students can run these before spending a single
API token.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory_agent  # noqa: E402
import memory_starter  # noqa: E402
from memory_store import MemoryStore  # noqa: E402
from mock_client import SECRET_IN_PASTE  # noqa: E402


def available_policies():
    """Chapter 2's pattern: run the same cases against both implementations.

    The starter joins in as soon as TODO 2 stops raising NotImplementedError,
    so finishing the TODO automatically puts it under the same red team.
    """
    policies = [("solution", memory_agent.MemoryPolicy)]
    try:
        memory_starter.MemoryPolicy().validate_record(
            {"key": "probe", "value": "probe"}, MemoryStore()
        )
    except NotImplementedError:
        return policies
    except Exception:
        pass
    policies.append(("starter", memory_starter.MemoryPolicy))
    return policies


class TestWriteGate(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def gate(self, record):
        outcomes = {}
        for label, cls in available_policies():
            with self.subTest(implementation=label):
                outcomes[label] = cls().validate_record(record, self.store)
        # Assertions below run on the solution's verdict; the subTest above
        # already failed loudly if the starter disagreed in a breaking way.
        for label, (ok, reason) in outcomes.items():
            if label != "solution":
                solution_ok, _ = outcomes["solution"]
                self.assertEqual(
                    ok, solution_ok,
                    f"{label} gate disagrees with the solution on {record!r}: {reason}",
                )
        return outcomes["solution"]

    def test_accepts_a_clean_record(self):
        ok, reason = self.gate({"key": "fine_per_violation", "value": "250"})
        self.assertTrue(ok, reason)

    def test_rejects_the_pasted_api_key(self):
        ok, reason = self.gate({"key": "zai_api_key", "value": SECRET_IN_PASTE})
        self.assertFalse(ok)
        self.assertEqual(reason, "secret")

    def test_rejects_a_secret_hidden_in_an_innocent_key(self):
        # The extractor does not have to name the field helpfully.
        ok, reason = self.gate({"key": "ci_notes", "value": f"key is {SECRET_IN_PASTE}"})
        self.assertFalse(ok)
        self.assertEqual(reason, "secret")

    def test_rejects_other_credential_shapes(self):
        for value in (
            "ghp_1234567890abcdefghij",
            "AKIAIOSFODNN7EXAMPLE",
            "password=hunter2hunter2",
        ):
            with self.subTest(value=value):
                ok, _ = self.gate({"key": "config", "value": value})
                self.assertFalse(ok, f"{value!r} should have been rejected")

    def test_rejects_missing_value(self):
        ok, reason = self.gate({"key": "note"})
        self.assertFalse(ok)
        self.assertEqual(reason, "missing value")

    def test_rejects_null_value(self):
        ok, reason = self.gate({"key": "note", "value": None})
        self.assertFalse(ok)
        self.assertEqual(reason, "missing value")

    def test_rejects_a_placeholder_value(self):
        """A real model will extract the '...' placeholder it saw in the task."""
        ok, _ = self.gate({"key": "fine_per_violation", "value": "..."})
        self.assertFalse(ok)

    def test_rejects_missing_key(self):
        ok, reason = self.gate({"value": "3.11"})
        self.assertFalse(ok)
        self.assertEqual(reason, "missing key")

    def test_rejects_two_facts_in_one_record(self):
        ok, reason = self.gate({"key": "audit_scope", "value": "the ServerRoom and the Lab"})
        self.assertFalse(ok)
        self.assertEqual(reason, "two facts in one record")

    def test_the_gate_does_not_judge_against_stored_state(self):
        """Admissibility only. What the store already holds is reconcile's call.

        An exact duplicate is the NOOP verdict and a changed value is UPDATE -
        both are decisions about state. If the gate rejected either one, that
        verdict would become unreachable and the update step would be missing a
        branch it is supposed to own.
        """
        self.store.add({"key": "fine_per_violation", "value": "200"})
        for value in ("200", "250"):
            with self.subTest(value=value):
                ok, reason = self.gate({"key": "fine_per_violation", "value": value})
                self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
