"""The red-team suite. Both the reference sandbox and the student's must pass."""

import tempfile
import unittest
from pathlib import Path

import grader
import sandbox
import starter_tools
from redteam import ATTACKS, build_attack_workspace, run_attacks


def available_resolvers():
    resolvers = [("solution", sandbox.resolve_safe_path)]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            starter_tools.resolve_safe_path(root, ".")
        except NotImplementedError:
            return resolvers
        except Exception:
            pass
    resolvers.append(("starter", starter_tools.resolve_safe_path))
    return resolvers


class SandboxTests(unittest.TestCase):
    def test_every_attack_is_blocked(self):
        for label, resolve in available_resolvers():
            with tempfile.TemporaryDirectory() as tmp:
                root = build_attack_workspace(Path(tmp))
                results = run_attacks(resolve, root)
            self.assertEqual(len(results), len(ATTACKS))
            for row in results:
                with self.subTest(implementation=label, attack=row["attack"]):
                    self.assertTrue(row["blocked"], row["detail"])

    def test_legitimate_paths_still_resolve(self):
        for label, resolve in available_resolvers():
            with tempfile.TemporaryDirectory() as tmp:
                root = build_attack_workspace(Path(tmp))
                with self.subTest(implementation=label):
                    self.assertTrue(resolve(root, "logs/sample.csv", must_exist=True).is_file())
                    self.assertEqual(resolve(root, ".").resolve(), root.resolve())
                    self.assertEqual(
                        resolve(root, "reports/new.md").parent.name,
                        "reports",
                    )

    def test_a_resolver_that_refuses_everything_scores_zero(self):
        def refuse_everything(root, user_path, *, must_exist=False):
            raise RuntimeError("no")

        grade = grader.grade_sandbox(refuse_everything)
        self.assertEqual(grade.score, 0)
        self.assertTrue(any("Legitimate path" in item for item in grade.feedback))

    def test_missing_file_is_reported_when_required(self):
        for label, resolve in available_resolvers():
            with tempfile.TemporaryDirectory() as tmp:
                root = build_attack_workspace(Path(tmp))
                with self.subTest(implementation=label):
                    with self.assertRaises(Exception):
                        resolve(root, "does_not_exist.csv", must_exist=True)


if __name__ == "__main__":
    unittest.main()
