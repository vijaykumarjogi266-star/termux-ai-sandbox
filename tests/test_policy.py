import os
import unittest
from agent.policy import ApprovalEngine, PolicyDecision


class TestApprovalEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ApprovalEngine()

    # 1. Tests for PolicyDecision.AUTO_APPROVE
    def test_auto_approve_allowed_single_file(self):
        decision = self.engine.evaluate_changes(["solution.py"])
        self.assertEqual(decision, PolicyDecision.AUTO_APPROVE)

    def test_auto_approve_allowed_directory_file(self):
        decision = self.engine.evaluate_changes(["sandbox/test_script.py"])
        self.assertEqual(decision, PolicyDecision.AUTO_APPROVE)

    def test_auto_approve_multiple_safe_files(self):
        decision = self.engine.evaluate_changes(["sandbox/main.py", "solution.py"])
        self.assertEqual(decision, PolicyDecision.AUTO_APPROVE)

    def test_auto_approve_empty_list(self):
        decision = self.engine.evaluate_changes([])
        self.assertEqual(decision, PolicyDecision.AUTO_APPROVE)

    # 2. Tests for PolicyDecision.REJECT
    def test_reject_protected_policy_file(self):
        decision = self.engine.evaluate_changes(["agent/policy.py"])
        self.assertEqual(decision, PolicyDecision.REJECT)

    def test_reject_protected_env_file(self):
        decision = self.engine.evaluate_changes([".env"])
        self.assertEqual(decision, PolicyDecision.REJECT)

    def test_reject_outside_allowed_path(self):
        decision = self.engine.evaluate_changes(["unauthorized_script.py"])
        self.assertEqual(decision, PolicyDecision.REJECT)

    def test_reject_mixed_batch_with_protected_file(self):
        decision = self.engine.evaluate_changes(["sandbox/solution.py", "agent/policy.py"])
        self.assertEqual(decision, PolicyDecision.REJECT)

    def test_reject_mixed_batch_with_unauthorized_file(self):
        decision = self.engine.evaluate_changes(["sandbox/solution.py", "/etc/passwd"])
        self.assertEqual(decision, PolicyDecision.REJECT)

    # 3. Tests for PolicyDecision.HUMAN_REQUIRED
    def test_human_required_deploy_script(self):
        decision = self.engine.evaluate_changes(["sandbox/deploy.sh"])
        self.assertEqual(decision, PolicyDecision.HUMAN_REQUIRED)

    def test_human_required_production_config(self):
        decision = self.engine.evaluate_changes(["sandbox/production.yaml"])
        self.assertEqual(decision, PolicyDecision.HUMAN_REQUIRED)

    def test_human_required_dockerfile(self):
        decision = self.engine.evaluate_changes(["sandbox/Dockerfile"])
        self.assertEqual(decision, PolicyDecision.HUMAN_REQUIRED)

    def test_human_required_infra_changes(self):
        decision = self.engine.evaluate_changes(["sandbox/infra/main.tf"])
        self.assertEqual(decision, PolicyDecision.HUMAN_REQUIRED)

    def test_human_required_mixed_safe_and_deploy(self):
        decision = self.engine.evaluate_changes(["sandbox/solution.py", "sandbox/deploy.py"])
        self.assertEqual(decision, PolicyDecision.HUMAN_REQUIRED)

    # 4. Custom paths configuration tests
    def test_custom_allowed_and_protected_paths(self):
        custom_engine = ApprovalEngine(
            allowed_paths=["src/"],
            protected_paths=["src/secret.py"]
        )
        self.assertEqual(
            custom_engine.evaluate_changes(["src/worker.py"]),
            PolicyDecision.AUTO_APPROVE
        )
        self.assertEqual(
            custom_engine.evaluate_changes(["src/secret.py"]),
            PolicyDecision.REJECT
        )
        self.assertEqual(
            custom_engine.evaluate_changes(["sandbox/solution.py"]),
            PolicyDecision.REJECT
        )

    def test_glob_pattern_matching(self):
        engine = ApprovalEngine(allowed_paths=["*.py", "docs/*"], protected_paths=["*.env"])
        self.assertEqual(engine.evaluate_changes(["helper.py"]), PolicyDecision.AUTO_APPROVE)
        self.assertEqual(engine.evaluate_changes(["docs/readme.txt"]), PolicyDecision.AUTO_APPROVE)
        self.assertEqual(engine.evaluate_changes(["secret.env"]), PolicyDecision.REJECT)
        self.assertEqual(engine.evaluate_changes(["random.bin"]), PolicyDecision.REJECT)

    def test_dynamic_path_addition(self):
        engine = ApprovalEngine(allowed_paths=["sandbox/"], protected_paths=[".env"])
        self.assertEqual(engine.evaluate_changes(["custom.py"]), PolicyDecision.REJECT)
        engine.add_allowed_path("custom.py")
        self.assertEqual(engine.evaluate_changes(["custom.py"]), PolicyDecision.AUTO_APPROVE)
        engine.add_protected_path("custom.py")
        self.assertEqual(engine.evaluate_changes(["custom.py"]), PolicyDecision.REJECT)

    def test_json_config_roundtrip(self):
        import tempfile
        engine = ApprovalEngine(allowed_paths=["custom/"], protected_paths=["custom/lock"])
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            cfg_path = tf.name
        try:
            engine.save_config(cfg_path)
            loaded = ApprovalEngine.load_from_config(cfg_path)
            self.assertEqual(loaded.allowed_paths, ["custom/"])
            self.assertEqual(loaded.protected_paths, ["custom/lock"])
        finally:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)


if __name__ == "__main__":
    unittest.main()

