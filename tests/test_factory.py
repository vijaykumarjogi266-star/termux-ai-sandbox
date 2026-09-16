import os
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import subprocess

from agent.policy import ApprovalEngine, PolicyDecision
from agent.orchestrator import Orchestrator
from agent.factory import FactoryRunner, FactoryState, AuditLogger


class TestFactory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = self.temp_dir.name
        self.audit_file = os.path.join(self.workspace_dir, "audit.jsonl")
        self.approval_engine = ApprovalEngine()
        self.orchestrator = Orchestrator(
            workspace_dir=self.workspace_dir,
            approval_engine=self.approval_engine,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _read_audit_events(self):
        if not os.path.exists(self.audit_file):
            return []
        events = []
        with open(self.audit_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line.strip()))
        return events

    @patch("subprocess.run")
    def test_output_pass_and_audit_log(self, mock_subprocess):
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(args=["git", "rev-parse", "HEAD"], returncode=0, stdout="abc123commit\n", stderr=""),
            subprocess.CompletedProcess(args=["agy", "--print", "--prompt", "Step 1: Test"], returncode=0, stdout="Success", stderr=""),
            subprocess.CompletedProcess(args=["git", "status", "--porcelain"], returncode=0, stdout=" M sandbox/solution.py\n", stderr=""),
        ]

        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
        )

        state = runner.run_task(prompt="Step 1: Test")
        self.assertEqual(state, FactoryState.PASS)

        # Verify audit log entries
        events = self._read_audit_events()
        event_types = [e["event_type"] for e in events]
        self.assertIn("git_checkpoint", event_types)
        self.assertIn("task_started", event_types)
        self.assertIn("steps_parsed", event_types)
        self.assertIn("step_started", event_types)
        self.assertIn("policy_evaluation", event_types)
        self.assertIn("task_finished", event_types)

        # Verify checkpoint SHA recorded in audit log
        checkpoint_event = next(e for e in events if e["event_type"] == "git_checkpoint")
        self.assertEqual(checkpoint_event["details"]["commit_sha"], "abc123commit")

        # Verify final state in audit log
        finished_event = next(e for e in events if e["event_type"] == "task_finished")
        self.assertEqual(finished_event["details"]["state"], "PASS")

    @patch("subprocess.run")
    def test_output_reject_protected_file(self, mock_subprocess):
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(args=["git", "rev-parse", "HEAD"], returncode=0, stdout="commit_sha\n", stderr=""),
            subprocess.CompletedProcess(args=["agy", "--print", "--prompt", "Step 1"], returncode=0, stdout="Success", stderr=""),
            subprocess.CompletedProcess(args=["git", "status", "--porcelain"], returncode=0, stdout=" M agent/policy.py\n", stderr=""),
        ]

        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
        )

        state = runner.run_task(prompt="Step 1: Modify policy")
        self.assertEqual(state, FactoryState.REJECT)

        events = self._read_audit_events()
        event_types = [e["event_type"] for e in events]
        self.assertIn("policy_rejection", event_types)
        finished_event = next(e for e in events if e["event_type"] == "task_finished")
        self.assertEqual(finished_event["details"]["state"], "REJECT")

    @patch("subprocess.run")
    def test_human_gate_rejected(self, mock_subprocess):
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(args=["git", "rev-parse", "HEAD"], returncode=0, stdout="commit_sha\n", stderr=""),
            subprocess.CompletedProcess(args=["agy", "--print", "--prompt", "Step 1"], returncode=0, stdout="Success", stderr=""),
            subprocess.CompletedProcess(args=["git", "status", "--porcelain"], returncode=0, stdout=" M sandbox/deploy.sh\n", stderr=""),
        ]

        # Simulate user rejecting with 'N'
        mock_input = MagicMock(return_value="N")
        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
            input_fn=mock_input,
        )

        state = runner.run_task(prompt="Step 1: Deploy to prod")
        self.assertEqual(state, FactoryState.HUMAN_REQUIRED)

        events = self._read_audit_events()
        event_types = [e["event_type"] for e in events]
        self.assertIn("human_gate_triggered", event_types)
        self.assertIn("human_gate_decision", event_types)

        gate_event = next(e for e in events if e["event_type"] == "human_gate_decision")
        self.assertFalse(gate_event["details"]["approved"])

    @patch("subprocess.run")
    def test_human_gate_approved_proceeds_to_pass(self, mock_subprocess):
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(args=["git", "rev-parse", "HEAD"], returncode=0, stdout="commit_sha\n", stderr=""),
            subprocess.CompletedProcess(args=["agy", "--print", "--prompt", "Step 1"], returncode=0, stdout="Success", stderr=""),
            subprocess.CompletedProcess(args=["git", "status", "--porcelain"], returncode=0, stdout=" M sandbox/deploy.sh\n", stderr=""),
        ]

        # Simulate user approving with 'Y'
        mock_input = MagicMock(return_value="Y")
        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
            input_fn=mock_input,
        )

        state = runner.run_task(prompt="Step 1: Deploy to prod")
        self.assertEqual(state, FactoryState.PASS)

        events = self._read_audit_events()
        gate_event = next(e for e in events if e["event_type"] == "human_gate_decision")
        self.assertTrue(gate_event["details"]["approved"])

    @patch("subprocess.run")
    def test_output_failed_unrecoverable_error(self, mock_subprocess):
        # 1. git rev-parse HEAD
        # 2. Step fails
        # 3. Heal prompt fails
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(args=["git", "rev-parse", "HEAD"], returncode=0, stdout="commit_sha\n", stderr=""),
            subprocess.CompletedProcess(args=["agy", "--print", "--prompt", "Step 1"], returncode=1, stdout="", stderr="Crash"),
            subprocess.CompletedProcess(args=["agy", "--print", "--prompt", "heal"], returncode=1, stdout="", stderr="Heal Failed"),
        ]

        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
        )

        state = runner.run_task(prompt="Step 1: Crash task")
        self.assertEqual(state, FactoryState.FAILED)

        events = self._read_audit_events()
        event_types = [e["event_type"] for e in events]
        self.assertIn("self_heal_failed", event_types)

    @patch("subprocess.run")
    def test_output_timeout(self, mock_subprocess):
        mock_subprocess.side_effect = [
            subprocess.CompletedProcess(args=["git", "rev-parse", "HEAD"], returncode=0, stdout="commit_sha\n", stderr=""),
            subprocess.TimeoutExpired(cmd=["agy"], timeout=5),
        ]

        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
        )

        state = runner.run_task(prompt="Step 1: Slow task")
        self.assertEqual(state, FactoryState.TIMEOUT)

        events = self._read_audit_events()
        event_types = [e["event_type"] for e in events]
        self.assertIn("timeout_expired", event_types)

    def test_generate_audit_report(self):
        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
        )
        runner.audit_logger.log("task_started", {"prompt": "Test"})
        runner.audit_logger.log("task_finished", {"state": "PASS"})

        report = runner.generate_audit_report()
        self.assertEqual(report["tasks_started"], 1)
        self.assertEqual(report["tasks_finished"], 1)
        self.assertEqual(report["outcomes"]["PASS"], 1)

    def test_run_doctor(self):
        runner = FactoryRunner(
            workspace_dir=self.workspace_dir,
            audit_file=self.audit_file,
            approval_engine=self.approval_engine,
            orchestrator=self.orchestrator,
        )
        doctor = runner.run_doctor()
        self.assertTrue(doctor["workspace_exists"])
        self.assertIn("git_initialized", doctor)
        self.assertIn("allowed_paths_count", doctor)


if __name__ == "__main__":
    unittest.main()

