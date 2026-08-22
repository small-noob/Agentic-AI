"""End-to-end offline runs, the role table, and the lesson 2 sandbox regression."""

import json
import tempfile
import unittest
from pathlib import Path

import lesson2  # noqa: F401  (appends 02Tools to sys.path; see lesson2.py)

import starter_harness

try:
    import harness  # the reference; absent from the student package
except ModuleNotFoundError:
    harness = None
from actions import ActionSystem, build_action_tools
from events import EventLog
from grader import READ_TOOLS, grade_run
from main import flow_plan, flow_single
from mock_client import ScriptedMockClient
from redteam import build_attack_workspace, run_attacks, run_legitimate
from roles import ACTION_TOOLS, REMEDIATOR, ROLE_SPECS, RunContext
from sandbox import resolve_safe_path
from skill_loader import discover_skills
from task import INJECTED_ACTION, SKILLS_DIR, UPSTREAM_ONLY_MARKERS, WORKSPACE_ROOT


def available_harnesses():
    found = [("solution", harness)] if harness else []
    try:
        starter_harness.validate_plan({"tasks": []}, None)
    except NotImplementedError:
        return found
    except Exception:
        pass
    found.append(("starter", starter_harness))
    return found


def make_context(impl):
    log = EventLog()
    return RunContext(
        workspace=WORKSPACE_ROOT,
        actions=ActionSystem(log=log, roster_path=WORKSPACE_ROOT / "employees.json"),
        log=log,
        skills=discover_skills(SKILLS_DIR),
        validate_plan=impl.validate_plan,
    )


class RoleTableTests(unittest.TestCase):
    """The boundary is declared here, so it is worth asserting on directly."""

    def test_the_remediator_has_no_way_to_read_anything(self):
        self.assertEqual(set(ROLE_SPECS[REMEDIATOR].tools) & READ_TOOLS, set())

    def test_only_the_remediator_and_the_baseline_can_act(self):
        for name, spec in ROLE_SPECS.items():
            can_act = bool(set(spec.tools) & set(ACTION_TOOLS))
            self.assertEqual(
                can_act, name in {"remediator", "single"},
                f"role '{name}' should {'' if name in {'remediator', 'single'} else 'not '}hold actions",
            )

    def test_the_planner_cannot_act_and_cannot_browse(self):
        tools = set(ROLE_SPECS["planner"].tools)
        self.assertEqual(tools & set(ACTION_TOOLS), set())
        self.assertEqual(tools, {"read_file"})


class FullRunTests(unittest.TestCase):
    def test_the_full_run_scores_everything(self):
        for label, impl in available_harnesses():
            with self.subTest(implementation=label):
                ctx = make_context(impl)
                outcome = flow_plan(ScriptedMockClient(), ctx, impl, max_attempts=3)
                grade = grade_run(
                    ctx.log, mode="full", plan=outcome.get("plan"),
                    findings=ctx.findings, validate_plan=impl.validate_plan,
                )
                self.assertEqual(
                    grade.score, 30,
                    f"{label}: {[line for item in grade.items for line in item.feedback]}",
                )

    def test_the_three_faults_end_where_they_should(self):
        for label, impl in available_harnesses():
            with self.subTest(implementation=label):
                ctx = make_context(impl)
                statuses = flow_plan(ScriptedMockClient(), ctx, impl, max_attempts=3)["statuses"]
                self.assertEqual(sorted(statuses.values()).count("ok"), 5)
                self.assertEqual(sorted(statuses.values()).count("terminal"), 1)

    def test_without_retries_the_repairable_faults_stay_broken(self):
        """Part 2 alone cannot finish the run. That is what part 3 is for."""

        for label, impl in available_harnesses():
            with self.subTest(implementation=label):
                ctx = make_context(impl)
                statuses = flow_plan(ScriptedMockClient(), ctx, impl, max_attempts=1)["statuses"]
                self.assertIn("exhausted", statuses.values())


class BaselineTests(unittest.TestCase):
    def test_the_single_agent_obeys_the_planted_instruction(self):
        """If this ever passes, the injection in handover.txt has stopped working."""

        for label, impl in available_harnesses():
            with self.subTest(implementation=label):
                ctx = make_context(impl)
                flow_single(ScriptedMockClient(), ctx)
                self.assertIn(INJECTED_ACTION, ctx.log.action_pairs(only_ok=False))

    def test_the_pipeline_does_not(self):
        for label, impl in available_harnesses():
            with self.subTest(implementation=label):
                ctx = make_context(impl)
                impl.run_pipeline(ScriptedMockClient(), ctx)
                self.assertNotIn(INJECTED_ACTION, ctx.log.action_pairs(only_ok=False))

    def test_the_pipeline_keeps_upstream_text_away_from_the_remediator(self):
        for label, impl in available_harnesses():
            with self.subTest(implementation=label):
                ctx = make_context(impl)
                impl.run_pipeline(ScriptedMockClient(), ctx)
                seen = ctx.log.text_seen_by(REMEDIATOR)
                for marker in UPSTREAM_ONLY_MARKERS:
                    self.assertNotIn(marker, seen)


class ActionServiceTests(unittest.TestCase):
    """The three planted faults behave as the assignment says they do."""

    def services(self):
        log = EventLog()
        system = ActionSystem(log=log, roster_path=WORKSPACE_ROOT / "employees.json")
        return build_action_tools(system), log

    def test_f1_is_transient_and_the_same_call_then_works(self):
        registry, _ = self.services()
        self.assertIn("503", registry.call("open_ticket", {"badge_id": "B1003", "door": "D2"}))
        self.assertTrue(json.loads(registry.call("open_ticket", {"badge_id": "B1003", "door": "D2"}))["ok"])

    def test_f2_carries_its_own_fix_in_the_error(self):
        registry, _ = self.services()
        output = registry.call("notify_manager", {"badge_id": "B1006", "manager_id": "Jon Pak"})
        self.assertIn("400", output)
        self.assertIn("M-02", output, "the error must name the valid ids, or no retry can repair it")
        self.assertTrue(json.loads(
            registry.call("notify_manager", {"badge_id": "B1006", "manager_id": "M-02"}))["ok"])

    def test_f3_never_becomes_a_success_however_often_it_is_retried(self):
        registry, _ = self.services()
        for _ in range(3):
            self.assertIn("410", registry.call("revoke_badge", {"badge_id": "B1005"}))

    def test_an_active_badge_can_still_be_revoked(self):
        """A guard that refuses everything is not a guard."""

        registry, _ = self.services()
        self.assertTrue(json.loads(registry.call("revoke_badge", {"badge_id": "B1002"}))["ok"])

    def test_reissuing_a_completed_action_is_refused_and_leaves_a_trace(self):
        registry, log = self.services()
        registry.call("notify_manager", {"badge_id": "B1006", "manager_id": "M-02"})
        self.assertIn("409 duplicate",
                      registry.call("notify_manager", {"badge_id": "B1006", "manager_id": "M-02"}))
        self.assertEqual(sum(1 for e in log.of_kind("action") if not e["ok"]), 1)


class SandboxRegressionTests(unittest.TestCase):
    """Lesson 2's rule: every time a lesson adds tools, rerun the red team."""

    def test_the_path_sandbox_still_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_attack_workspace(Path(tmp))
            attacks = run_attacks(resolve_safe_path, root)
            legitimate = run_legitimate(resolve_safe_path, root)
        staged = [row for row in attacks if not row.get("skipped")]
        self.assertTrue(all(row["blocked"] for row in staged))
        self.assertTrue(all(row["allowed"] for row in legitimate))


if __name__ == "__main__":
    unittest.main()
