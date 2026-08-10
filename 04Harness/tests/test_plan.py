"""``validate_plan`` — run against the reference and, once written, yours.

A plan comes out of a language model, so it is untrusted input. These cases are
the plan-shaped equivalent of lesson 2's ten sandbox attacks: half of them must
be rejected, and the last one must still be allowed through.
"""

import copy
import unittest

import starter_harness

try:
    import harness  # the reference; absent from the student package
except ModuleNotFoundError:
    harness = None
from mock_client import PLAN
from task import EXPECTED_FINDINGS


def available_validators():
    validators = [("solution", harness.validate_plan)] if harness else []
    try:
        starter_harness.validate_plan({"tasks": []}, None)
    except NotImplementedError:
        return validators
    except Exception:
        pass
    validators.append(("starter", starter_harness.validate_plan))
    return validators


def _skip_if_nothing_to_test(case, found):
    if not found:
        case.skipTest("write the TODO first; there is nothing to check yet")


def plan_with(**changes):
    plan = copy.deepcopy(PLAN)
    if "tasks" in changes:
        plan["tasks"] = changes["tasks"]
    return plan


class PlanValidationTests(unittest.TestCase):
    def assertRejected(self, plan, why):
        for label, validate in available_validators():
            with self.subTest(implementation=label):
                self.assertTrue(
                    validate(plan, EXPECTED_FINDINGS),
                    f"{label}: should have rejected this plan — {why}",
                )

    def test_the_reference_plan_is_accepted(self):
        for label, validate in available_validators():
            with self.subTest(implementation=label):
                self.assertEqual(
                    validate(copy.deepcopy(PLAN), EXPECTED_FINDINGS), [],
                    f"{label}: a validator that rejects the correct plan blocks every run",
                )

    def test_rejects_a_non_object(self):
        self.assertRejected(["revoke B1005"], "the plan is not an object")

    def test_rejects_an_empty_task_list(self):
        self.assertRejected({"tasks": []}, "there is nothing to do")

    def test_rejects_an_unknown_action(self):
        tasks = copy.deepcopy(PLAN["tasks"])
        tasks[0]["action"] = "delete_directory"
        self.assertRejected(plan_with(tasks=tasks), "delete_directory is not a remediation action")

    def test_rejects_a_missing_argument(self):
        tasks = copy.deepcopy(PLAN["tasks"])
        del tasks[1]["manager_id"]
        self.assertRejected(plan_with(tasks=tasks), "the remediator cannot look up a manager_id")

    def test_rejects_the_same_action_twice_for_one_badge(self):
        tasks = copy.deepcopy(PLAN["tasks"])
        duplicate = copy.deepcopy(tasks[0])
        duplicate["id"] = "t7"
        tasks.append(duplicate)
        self.assertRejected(plan_with(tasks=tasks), "seven records are still one revoke")

    def test_rejects_a_duplicate_task_id(self):
        """Ids are optional, but two tasks claiming the same one is still wrong."""

        tasks = copy.deepcopy(PLAN["tasks"])
        tasks[0]["id"] = tasks[1]["id"] = "same"
        self.assertRejected(plan_with(tasks=tasks), "two tasks share an id")

    def test_rejects_a_badge_that_is_not_in_the_findings(self):
        tasks = copy.deepcopy(PLAN["tasks"])
        tasks.append({"action": "revoke_badge", "badge_id": "B1007"})
        self.assertRejected(plan_with(tasks=tasks), "B1007 never violated anything")

    def test_rejects_an_action_the_badges_reasons_do_not_map_to(self):
        """This is the injected action. B1002 was out of hours once: notify, not revoke."""

        tasks = copy.deepcopy(PLAN["tasks"])
        tasks.append({"action": "revoke_badge", "badge_id": "B1002"})
        self.assertRejected(plan_with(tasks=tasks), "outside_allowed_hours does not map to revoke")

    def test_rejects_an_absurdly_long_plan(self):
        tasks = [dict(copy.deepcopy(PLAN["tasks"][5]), id=f"x{i}") for i in range(30)]
        self.assertRejected(plan_with(tasks=tasks), "the plan is past the task ceiling")


class StarterChecklistTests(unittest.TestCase):
    """Red until the TODOs are done. This suite is your checklist."""

    def test_todo_1_spawn_is_implemented(self):
        try:
            starter_harness.spawn(None, "investigator", "", None)
        except NotImplementedError as exc:
            self.fail(f"TODO 1a is not done: {exc}")
        except Exception:
            pass  # any other error means the function exists and ran

    def test_todo_2_validate_plan_is_implemented(self):
        try:
            starter_harness.validate_plan({"tasks": []}, None)
        except NotImplementedError as exc:
            self.fail(f"TODO 2a is not done: {exc}")
        except Exception:
            pass

    def test_todo_3_classify_failure_is_implemented(self):
        try:
            starter_harness.classify_failure("503 service_busy: x")
        except NotImplementedError as exc:
            self.fail(f"TODO 3a is not done: {exc}")
        except Exception:
            pass


class ClassifyFailureTests(unittest.TestCase):
    def implementations(self):
        found = [("solution", harness.classify_failure)] if harness else []
        try:
            starter_harness.classify_failure("503 x")
        except NotImplementedError:
            return found
        except Exception:
            pass
        found.append(("starter", starter_harness.classify_failure))
        return found

    def test_transient_and_repairable_failures_are_retryable(self):
        for label, classify in self.implementations():
            with self.subTest(implementation=label):
                self.assertEqual(classify("503 service_busy: nothing was filed"), "retryable")
                self.assertEqual(classify("400 bad_argument: unknown manager_id 'x'"), "retryable")

    def test_settled_requests_are_terminal(self):
        for label, classify in self.implementations():
            with self.subTest(implementation=label):
                self.assertEqual(classify("410 already_revoked: badge B1005 ..."), "terminal")
                self.assertEqual(classify("409 duplicate: revoke_badge for B1005 ..."), "terminal")


if __name__ == "__main__":
    unittest.main()
