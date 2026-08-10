import shutil
import tempfile
import unittest
from pathlib import Path

import agent_tools
import starter_tools
from redteam import SECRET_MARKER, build_attack_workspace
from task import WORKSPACE_ROOT


def available_builders():
    builders = [("solution", agent_tools.build_workspace_tools)]
    with tempfile.TemporaryDirectory() as tmp:
        registry = starter_tools.build_workspace_tools(Path(tmp))
        if {"list_files", "read_file", "write_file"} <= set(registry.tools):
            builders.append(("starter", starter_tools.build_workspace_tools))
    return builders


class StarterChecklistTests(unittest.TestCase):
    """Fails until the starter's TODOs are done. This is the student's checklist."""

    def test_todo_2_every_description_is_written(self):
        registry = starter_tools.build_workspace_tools(WORKSPACE_ROOT)
        unwritten = sorted(
            name
            for name, spec in registry.tools.items()
            if "TODO" in spec.description
            or any("TODO" in arg.get("description", "") for arg in spec.parameters["properties"].values())
        )
        self.assertEqual(unwritten, [], f"TODO 2: these tools still have placeholder descriptions: {unwritten}")

    def test_todo_3_list_files_is_registered(self):
        registry = starter_tools.build_workspace_tools(WORKSPACE_ROOT)
        self.assertIn("list_files", registry.tools, "TODO 3: no list_files tool has been registered yet")


class WorkspaceToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        shutil.copytree(WORKSPACE_ROOT, self.root)
        self.addCleanup(self.tmp.cleanup)

    def test_reads_and_lists_workspace_files(self):
        for label, build in available_builders():
            registry = build(self.root)
            with self.subTest(implementation=label):
                self.assertIn("policy.json", registry.call("list_files", {"path": "."}))
                self.assertIn("min_clearance", registry.call("read_file", {"path": "policy.json"}))

    def test_read_is_truncated_and_says_so(self):
        for label, build in available_builders():
            registry = build(self.root)
            with self.subTest(implementation=label):
                output = registry.call("read_file", {"path": "policy.json", "max_bytes": 40})
                self.assertIn("truncated", output)

    def test_write_creates_parent_folders(self):
        for label, build in available_builders():
            registry = build(self.root)
            with self.subTest(implementation=label):
                registry.call("write_file", {"path": "reports/audit.md", "content": "Suspect: B1005"})
                self.assertEqual((self.root / "reports" / "audit.md").read_text(), "Suspect: B1005")

    def test_tools_refuse_to_escape_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_attack_workspace(Path(tmp))
            for label, build in available_builders():
                registry = build(root)
                for path in ("../secrets.env", "/etc/passwd", "escape_secrets", "logs/../../secrets.env"):
                    with self.subTest(implementation=label, path=path):
                        output = registry.call("read_file", {"path": path})
                        self.assertNotIn(SECRET_MARKER, output)
                        self.assertIn("Tool error", output)
                with self.subTest(implementation=label, path="write ../pwned.txt"):
                    self.assertIn("Tool error", registry.call("write_file", {"path": "../pwned.txt", "content": "x"}))
                    self.assertFalse((Path(tmp) / "outer" / "pwned.txt").exists())

    def test_calculator_carries_over_from_lesson_one(self):
        for label, build in available_builders():
            registry = build(self.root)
            with self.subTest(implementation=label):
                self.assertEqual(
                    registry.call("calculate", {"expression": "(11 * 9176 + 1005 * 31337) % 1000000"}),
                    "594621",
                )
                self.assertIn("Tool error", registry.call("calculate", {"expression": "__import__('os')"}))


if __name__ == "__main__":
    unittest.main()
