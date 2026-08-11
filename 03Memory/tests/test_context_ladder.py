"""TODO 4: the ladder must climb in order, and must refuse rather than lie."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory_starter  # noqa: E402
from memory_agent import MAX_MESSAGE_TOKENS, MemoryPolicy  # noqa: E402
from memory_store import MemoryStore  # noqa: E402
from mock_client import MockClient  # noqa: E402
from react_loop import ContextOverflow  # noqa: E402
from sessions import EXPORTER_ENV_PASTE  # noqa: E402
from tokens import count_messages, count_tokens  # noqa: E402

SYSTEM = "You are the audit assistant."


def _starter_todo4_started() -> bool:
    """True once build_context stops raising NotImplementedError.

    (trim_oversized is provided, so it cannot be the probe: it never raises.)
    """
    try:
        memory_starter.MemoryPolicy().build_context(
            None, "system", MemoryStore(), [], budget=10**9
        )
    except NotImplementedError:
        return False
    except Exception:
        pass
    return True


def turns(n: int, words: int = 40) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "filler " * words}
        for i in range(n)
    ]


class TestLadder(unittest.TestCase):
    def setUp(self):
        self.policy = MemoryPolicy()
        self.max_message_tokens = MAX_MESSAGE_TOKENS
        self.client = MockClient()
        self.store = MemoryStore()

    def build(self, history, budget):
        return self.policy.build_context(self.client, SYSTEM, self.store, history, budget)

    def test_l0_when_everything_fits(self):
        assembled = self.build(turns(2, words=5), budget=4000)
        self.assertEqual(len(assembled.ladder), 1)
        self.assertTrue(assembled.ladder[0].startswith("L0"))
        self.assertEqual(self.policy.max_ladder_rung, 0)
        self.assertEqual(self.policy.compactions, 0)

    def test_never_exceeds_the_budget_it_returns(self):
        assembled = self.build(turns(30), budget=1500)
        self.assertLessEqual(assembled.tokens, 1500)
        self.assertEqual(assembled.tokens, count_messages(assembled.messages))

    def test_l1_trims_an_oversized_paste_without_dropping_it(self):
        history = [{"role": "user", "content": "Exporter config:\n" + EXPORTER_ENV_PASTE}]
        assembled = self.build(history, budget=250)
        self.assertTrue(any(line.startswith("L1") for line in assembled.ladder))
        # The message is still there, just shorter, and it says so.
        body = assembled.messages[-1]["content"]
        self.assertIn("trimmed", body)
        self.assertIn("BADGE_EXPORT_SOURCE=door-controller-3", body)
        self.assertEqual(len(assembled.messages), 2)  # system + the one turn

    def test_l1_runs_before_l2(self):
        """Cheap and lossless before expensive and lossy - slide 39's ordering."""
        history = [{"role": "user", "content": "env:\n" + EXPORTER_ENV_PASTE}]
        assembled = self.build(history, budget=250)
        rungs = [line.split()[0] for line in assembled.ladder]
        self.assertEqual(rungs[:2], ["L0", "L1"])
        self.assertEqual(self.policy.compactions, 0, "L1 alone sufficed; no API call needed")

    def test_l2_compacts_and_costs_one_api_call(self):
        assembled = self.build(turns(20), budget=900)
        self.assertTrue(any(line.startswith("L2") for line in assembled.ladder))
        self.assertGreaterEqual(self.policy.compactions, 1)
        self.assertTrue(assembled.messages[1]["content"].startswith("[compacted"))

    def test_current_turn_stays_verbatim_after_compaction(self):
        history = turns(20)
        history[-1] = {"role": "user", "content": "Return exactly {\"answer\":\"42\"}"}
        assembled = self.build(history, budget=900)
        self.assertEqual(assembled.messages[-1]["content"], history[-1]["content"])

    def test_overflow_when_the_budget_itself_is_too_small(self):
        # 200 sits below the L3 floor (one compacted note + the current turn)
        # for BOTH token estimators, so the ladder must refuse rather than lie.
        with self.assertRaises(ContextOverflow) as ctx:
            self.build(turns(40), budget=200)
        self.assertIn("200", str(ctx.exception))

    def test_digest_is_included_when_the_store_has_records(self):
        self.store.add({"key": "fine_per_violation", "value": "250", "source": "s1", "session": 1})
        assembled = self.build(turns(2, words=5), budget=4000)
        self.assertIn("fine_per_violation=250", assembled.messages[1]["content"])

    def test_trim_leaves_short_messages_alone(self):
        message = {"role": "user", "content": "short"}
        self.assertIs(self.policy.trim_oversized(message), message)

    def test_trim_actually_reduces_size(self):
        message = {"role": "user", "content": EXPORTER_ENV_PASTE}
        trimmed = self.policy.trim_oversized(message)
        self.assertLess(count_tokens(trimmed["content"]), count_tokens(EXPORTER_ENV_PASTE))
        self.assertLessEqual(count_tokens(trimmed["content"]), self.max_message_tokens * 2)


@unittest.skipUnless(_starter_todo4_started(), "starter TODO 4 not implemented yet")
class TestLadderStarter(TestLadder):
    """The same ladder contract, run against the student implementation.

    Chapter 2's pattern: as soon as the TODO stops raising, the starter faces
    exactly the tests the reference implementation faces.
    """

    def setUp(self):
        super().setUp()
        self.policy = memory_starter.MemoryPolicy()
        self.max_message_tokens = memory_starter.MAX_MESSAGE_TOKENS


if __name__ == "__main__":
    unittest.main()
