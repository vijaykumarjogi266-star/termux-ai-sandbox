import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import subprocess

from agent.policy import ApprovalEngine, PolicyDecision
from agent.orchestrator import Orchestrator
from agent.brain import Brain


class TestBrain(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = self.temp_dir.name
        self.inbox_dir = os.path.join(self.workspace_dir, "inbox")
        os.makedirs(self.inbox_dir, exist_ok=True)
        self.approval_engine = ApprovalEngine()
        self.brain = Brain(
            workspace_dir=self.workspace_dir,
            inbox_dir=self.inbox_dir,
            approval_engine=self.approval_engine,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_decompose_project_generates_discrete_steps(self):
        steps = self.brain.decompose_project(
            project_name="Data Parser",
            objective="Parse CSV files into JSON format",
            target_files=["sandbox/csv_parser.py"],
        )
        self.assertGreaterEqual(len(steps), 4)
        self.assertTrue(any("Data Parser" in s for s in steps))
        self.assertTrue(any("csv_parser.py" in s for s in steps))

    def test_validate_plan_safe_files(self):
        decision = self.brain.validate_plan(["sandbox/app.py"])
        self.assertEqual(decision, PolicyDecision.AUTO_APPROVE)

    def test_validate_plan_protected_files(self):
        decision = self.brain.validate_plan(["agent/policy.py"])
        self.assertEqual(decision, PolicyDecision.REJECT)

    def test_create_and_queue_task_success(self):
        file_path = self.brain.create_and_queue_task(
            project_name="Math Helper",
            objective="Add vector arithmetic utility",
            target_files=["sandbox/vector.py"],
        )
        self.assertTrue(os.path.exists(file_path))
        self.assertTrue(file_path.endswith(".txt"))
        self.assertTrue(os.path.dirname(file_path) == self.inbox_dir)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Math Helper", content)

        # Test compatibility with Orchestrator's step parser
        orch = Orchestrator(workspace_dir=self.workspace_dir, inbox_dir=self.inbox_dir)
        steps = orch.parse_steps(content)
        self.assertEqual(len(steps), 4)

    def test_create_and_queue_task_rejects_protected_files(self):
        with self.assertRaises(ValueError) as ctx:
            self.brain.create_and_queue_task(
                project_name="Sneaky Task",
                objective="Modify governance policy",
                target_files=["agent/policy.py"],
            )
        self.assertIn("violate policy", str(ctx.exception).lower())

    @patch("subprocess.run")
    def test_brain_orchestrator_integration(self, mock_subprocess):
        # Brain creates task file in inbox
        file_path = self.brain.create_and_queue_task(
            project_name="Integration Pipeline",
            objective="Test end-to-end flow",
            target_files=["sandbox/integration.py"],
            custom_steps=["Step 1: Build component", "Step 2: Verify component"],
        )

        # Mock agy and git execution for the 2 steps
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "Step 1: Build component"],
                returncode=0,
                stdout="Step 1 done",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M sandbox/integration.py\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "Step 2: Verify component"],
                returncode=0,
                stdout="Step 2 done",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M sandbox/integration.py\n",
                stderr="",
            ),
        ]

        orch = Orchestrator(
            workspace_dir=self.workspace_dir,
            inbox_dir=self.inbox_dir,
            approval_engine=self.approval_engine,
        )
        success = orch.process_file(file_path)
        self.assertTrue(success)
        self.assertIn(os.path.abspath(file_path), orch.processed_files)


if __name__ == "__main__":
    unittest.main()
