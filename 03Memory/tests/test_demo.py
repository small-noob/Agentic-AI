"""Part A end to end, offline. No API key, no cost, no network.

The mock agent is honest: it answers only from what is in its context. These
tests pin the demo's two outcomes - the tools run fails BECAUSE nothing
survives between sessions, the memory run passes BECAUSE two ~10-token facts
do. If someone edits the sessions and accidentally leaks a conversational
fact onto disk, test_tools_run_fails is the tripwire.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grader import finish_verifier, grade_demo  # noqa: E402
from memory_agent import MemoryPolicy, ToolsPolicy  # noqa: E402
from memory_store import MemoryStore  # noqa: E402
from mock_client import MockClient  # noqa: E402
from react_loop import run_sessions  # noqa: E402
from sessions import (  # noqa: E402
    AGENT_SYSTEM_TEMPLATE,
    EXPECTED_ANSWER,
    EXPECTED_DEMO_MEMORY,
    SESSIONS,
    WORKSPACE_ROOT,
    reset_workspace,
)
from tools import build_agent_registry  # noqa: E402


def run(policy, store):
    registry = build_agent_registry(WORKSPACE_ROOT)
    result = run_sessions(
        client=MockClient(),
        policy=policy,
        store=store,
        sessions=SESSIONS,
        system_prompt=AGENT_SYSTEM_TEMPLATE.format(tools=registry.describe()),
        registry=registry,
        verifier=finish_verifier,
        verbose=False,
        answer_keys=set(EXPECTED_ANSWER),
        on_session_start=lambda _n: reset_workspace(),
    )
    return result, registry


class TestToolsRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MemoryStore()
        cls.result, cls.registry = run(ToolsPolicy(), cls.store)

    def test_tools_run_fails(self):
        grade = grade_demo(self.result.answer, self.registry)
        self.assertFalse(grade.passed, "the tools-only run must fail - if it "
                         "passed, a conversational fact leaked onto disk")

    def test_it_never_produces_an_answer(self):
        self.assertIsNone(self.result.answer)

    def test_the_disk_half_still_works(self):
        # The tools are not broken: it can list and read files just fine.
        self.assertTrue(self.registry.called("list_files"))
        self.assertTrue(self.registry.called("read_file"))

    def test_the_store_stays_empty(self):
        self.assertEqual(self.store.all("*"), [])


class TestMemoryRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MemoryStore()
        cls.result, cls.registry = run(MemoryPolicy(), cls.store)

    def test_memory_run_passes(self):
        grade = grade_demo(self.result.answer, self.registry)
        self.assertTrue(grade.passed, grade.feedback)

    def test_the_answer_is_exact(self):
        self.assertEqual(self.result.answer, EXPECTED_ANSWER)

    def test_session_1_left_the_two_facts(self):
        for key, value in EXPECTED_DEMO_MEMORY.items():
            record = self.store.get(key)
            self.assertIsNotNone(record, f"{key} missing from the store")
            self.assertEqual(record["value"], value)

    def test_the_gate_rejected_the_junk_candidate(self):
        # The mock extractor emits a record with no value; the gate catches it.
        self.assertTrue(self.store.rejections)

    def test_the_total_was_computed_not_asserted(self):
        outputs = {
            e["output"] for e in self.registry.history
            if e["tool"] == "calculate" and e["ok"]
        }
        self.assertIn(EXPECTED_ANSWER["total_fine"], outputs)

    def test_the_incident_file_was_actually_read(self):
        reads = {
            str(e["arguments"].get("path", "")).lstrip("./")
            for e in self.registry.history
            if e["tool"] == "read_file" and e["ok"]
        }
        self.assertIn("incident_0812.txt", reads)


if __name__ == "__main__":
    unittest.main()
