import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call
import subprocess

from agent.policy import ApprovalEngine, PolicyDecision
from agent.orchestrator import (
    Orchestrator,
    PolicyViolationError,
    InboxFileEventHandler,
)
from watchdog.events import FileCreatedEvent


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = self.temp_dir.name
        self.inbox_dir = os.path.join(self.workspace_dir, "inbox")
        os.makedirs(self.inbox_dir, exist_ok=True)
        self.approval_engine = ApprovalEngine()
        self.orchestrator = Orchestrator(
            workspace_dir=self.workspace_dir,
            inbox_dir=self.inbox_dir,
            approval_engine=self.approval_engine,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_steps_line_by_line(self):
        content = "Step 1: Setup environment\nStep 2: Install dependencies\nStep 3: Run pipeline"
        steps = self.orchestrator.parse_steps(content)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0], "Step 1: Setup environment")
        self.assertEqual(steps[1], "Step 2: Install dependencies")
        self.assertEqual(steps[2], "Step 3: Run pipeline")

    def test_parse_steps_paragraph_delimited(self):
        content = "Step 1: First action.\nDetailed explanation.\n\nStep 2: Second action.\nWith notes."
        steps = self.orchestrator.parse_steps(content)
        self.assertEqual(len(steps), 2)
        self.assertIn("Step 1: First action", steps[0])
        self.assertIn("Step 2: Second action", steps[1])

    @patch("subprocess.run")
    def test_successful_step_execution(self, mock_subprocess):
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "Step 1"],
                returncode=0,
                stdout="Step 1 completed successfully",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M sandbox/solution.py\n",
                stderr="",
            ),
        ]

        result = self.orchestrator.execute_step("Step 1")
        self.assertTrue(result)
        mock_subprocess.assert_any_call(
            ["agy", "--print", "--prompt", "Step 1"],
            capture_output=True,
            text=True,
            cwd=self.workspace_dir,
            check=False,
        )

    @patch("subprocess.run")
    def test_self_healing_flow_on_error(self, mock_subprocess):
        # 1st call fails (step execution)
        # 2nd call succeeds (self-healing prompt)
        # 3rd call git status returns safe change
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "Step 1"],
                returncode=1,
                stdout="",
                stderr="NameError: name 'foo' is not defined",
            ),
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "heal"],
                returncode=0,
                stdout="Successfully fixed error and healed the step",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M sandbox/solution.py\n",
                stderr="",
            ),
        ]

        result = self.orchestrator.execute_step("Step 1")
        self.assertTrue(result)

        # Verify heal prompt was sent to agy
        heal_call = mock_subprocess.call_args_list[1]
        called_args = heal_call[0][0]
        self.assertEqual(called_args[0], "agy")
        self.assertEqual(called_args[1], "--print")
        self.assertEqual(called_args[2], "--prompt")
        self.assertIn("NameError", called_args[3])
        self.assertIn("self-heal", called_args[3].lower())

    @patch("subprocess.run")
    def test_governance_rejection_halts_execution(self, mock_subprocess):
        # Step succeeds, but modifies protected file agent/policy.py
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "Malicious step"],
                returncode=0,
                stdout="Done",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M agent/policy.py\n",
                stderr="",
            ),
        ]

        with self.assertRaises(PolicyViolationError):
            self.orchestrator.execute_step("Malicious step")

    @patch("subprocess.run")
    def test_process_file_end_to_end(self, mock_subprocess):
        # Test file with two steps
        test_file = os.path.join(self.inbox_dir, "task.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Step 1: Create solution\nStep 2: Test solution\n")

        # Mock responses for step 1 (agy + git status) and step 2 (agy + git status)
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "Step 1: Create solution"],
                returncode=0,
                stdout="Step 1 done",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M sandbox/solution.py\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["agy", "--print", "--prompt", "Step 2: Test solution"],
                returncode=0,
                stdout="Step 2 done",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=["git", "status", "--porcelain"],
                returncode=0,
                stdout=" M sandbox/solution.py\n",
                stderr="",
            ),
        ]

        success = self.orchestrator.process_file(test_file)
        self.assertTrue(success)
        self.assertIn(os.path.abspath(test_file), self.orchestrator.processed_files)

    def test_watchdog_event_handler_dispatches_txt_file(self):
        mock_orch = MagicMock()
        handler = InboxFileEventHandler(mock_orch)

        # Simulating file created event for .txt
        event_txt = FileCreatedEvent("/root/sandbox/inbox/new_task.txt")
        handler.on_created(event_txt)
        mock_orch.process_file.assert_called_once_with("/root/sandbox/inbox/new_task.txt")

        # Simulating non-txt file (e.g. .tmp) should be ignored
        mock_orch.reset_mock()
        event_non_txt = FileCreatedEvent("/root/sandbox/inbox/temp.tmp")
        handler.on_created(event_non_txt)
        mock_orch.process_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
