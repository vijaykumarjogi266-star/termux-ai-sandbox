import os
import json
import tempfile
import unittest
import subprocess

from agent.policy import ApprovalEngine, PolicyDecision
from agent.sandbox_proof import run_sandbox_proof


class TestSandboxProof(unittest.TestCase):
    def test_run_sandbox_proof(self):
        # Run the full automated proof
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        summary = run_sandbox_proof(workspace_dir)
        self.assertEqual(summary["status"], "SUCCESS")
        self.assertEqual(summary["c2_decision"], "AUTO_APPROVE")
        self.assertEqual(summary["c3_decision"], "REJECT")
        self.assertTrue(summary["protected_intact"])

        # Check audit log contains rejection event
        audit_file = os.path.join(workspace_dir, "audit.jsonl")
        self.assertTrue(os.path.exists(audit_file))
        rejection_found = False
        with open(audit_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line.strip())
                    if data.get("event_type") == "policy_rejection":
                        if "phase_c_proof/protected_mock.txt" in data.get("details", {}).get("violating_files", []):
                            rejection_found = True
        self.assertTrue(rejection_found, "Audit log must contain policy_rejection for protected_mock.txt")


if __name__ == "__main__":
    unittest.main()
