"""The store is given to students, so these tests document its contract."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_store import MemoryStore  # noqa: E402


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def test_add_then_get(self):
        self.store.add({"key": "test_files", "value": "8", "source": "session1", "session": 1})
        self.assertEqual(self.store.get("test_files")["value"], "8")

    def test_supersede_keeps_the_audit_trail(self):
        self.store.add({"key": "test_files", "value": "8", "source": "session1", "session": 1})
        self.store.supersede(
            "test_files", {"key": "test_files", "value": "10", "source": "session2", "session": 2}
        )
        self.assertEqual(self.store.get("test_files")["value"], "10")
        old = self.store.all("superseded")
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0]["value"], "8")
        # Nothing was physically removed.
        self.assertEqual(len(self.store.all("*")), 2)

    def test_soft_delete_removes_it_from_current_only(self):
        self.store.add({"key": "test_runner", "value": "docker", "source": "s1", "session": 1})
        self.assertTrue(self.store.soft_delete("test_runner", source="s2"))
        self.assertIsNone(self.store.get("test_runner"))
        self.assertEqual(len(self.store.all("deleted")), 1)

    def test_soft_delete_of_unknown_key_reports_failure(self):
        self.assertFalse(self.store.soft_delete("nope"))

    def test_digest_only_includes_current(self):
        self.store.add({"key": "a", "value": "1", "source": "s1", "session": 1})
        self.store.add({"key": "b", "value": "2", "source": "s1", "session": 1})
        self.store.soft_delete("b")
        digest = self.store.digest()
        self.assertIn("a=1", digest)
        self.assertNotIn("b=2", digest)

    def test_empty_digest_is_empty_string(self):
        self.assertEqual(self.store.digest(), "")


    def test_leaked_secrets_finds_a_planted_key(self):
        self.store.add({"key": "k", "value": "sk-proj-abcdefgh", "source": "s1", "session": 1})
        self.assertEqual(self.store.leaked_secrets(["sk-proj-", "ghp_"]), ["sk-proj-"])

    def test_round_trips_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(root=Path(tmp), relpath="memory.jsonl")
            store.add({"key": "test_files", "value": "8", "source": "s1", "session": 1})
            store.supersede(
                "test_files", {"key": "test_files", "value": "10", "source": "s2", "session": 2}
            )
            store.save()

            lines = (Path(tmp) / "memory.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["status"], "superseded")

            # This is what makes cross-session memory real rather than a variable.
            reloaded = MemoryStore.load(Path(tmp))
            self.assertEqual(reloaded.get("test_files")["value"], "10")

    def test_persistence_goes_through_the_chapter_two_sandbox(self):
        """The store is a file the harness writes, and files go through the door.

        Chapter 2's rule was 'every file tool routes through resolve_safe_path'.
        The rule does not care who is holding the pen, so a store aimed outside
        its root refuses to write rather than creating files anywhere on disk.
        """
        from sandbox import SandboxError  # resolves via lesson2.py

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(root=Path(tmp), relpath="../escaped.jsonl")
            store.add({"key": "a", "value": "1", "source": "s1", "session": 1})
            with self.assertRaises(SandboxError):
                store.save()


if __name__ == "__main__":
    unittest.main()
