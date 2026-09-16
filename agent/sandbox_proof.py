"""
Phase C: Sandbox Proof
Automated verification of safety controls and governance enforcement.
Proves allowed changes pass, unauthorized changes are strictly blocked,
audit logs are recorded, and the workspace reverts cleanly to checkpoint.
"""

import os
import sys
import json
import subprocess
from typing import Dict, Any

# Ensure parent directory is in sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from agent.policy import ApprovalEngine, PolicyDecision
from agent.factory import FactoryRunner, FactoryState, AuditLogger


def run_sandbox_proof(workspace_dir: str = "/root/sandbox") -> Dict[str, Any]:
    print("==================================================")
    print("       STARTING PHASE C: SANDBOX PROOF")
    print("==================================================")

    proof_dir = os.path.join(workspace_dir, "phase_c_proof")
    protected_file = os.path.join(proof_dir, "protected_mock.txt")
    allowed_file = os.path.join(proof_dir, "allowed_change.txt")
    audit_file = os.path.join(workspace_dir, "audit.jsonl")

    logger = AuditLogger(audit_file)
    engine = ApprovalEngine()

    # Step 1: Verify baseline
    print("\n[Step 1] Verifying baseline workspace and checkpoint...")
    assert os.path.exists(protected_file), f"Protected file missing: {protected_file}"
    with open(protected_file, "r", encoding="utf-8") as f:
        baseline_content = f.read().strip()

    git_res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
    )
    checkpoint_sha = git_res.stdout.strip()
    print(f" Baseline Git Checkpoint: {checkpoint_sha}")
    print(f" Protected file baseline content: '{baseline_content}'")
    logger.log("proof_started", {"checkpoint": checkpoint_sha, "protected_file": protected_file})

    # Step 2: Configuration verification
    print("\n[Step 2] Verifying policy configuration...")
    rel_protected = "phase_c_proof/protected_mock.txt"
    rel_allowed = "phase_c_proof/allowed_change.txt"
    assert engine.is_protected(rel_protected), f"{rel_protected} must be detected as protected"
    assert engine.is_allowed(rel_allowed), f"{rel_allowed} must be detected as allowed"
    assert not engine.is_protected(rel_allowed), f"{rel_allowed} must not be protected"
    print(f" Protected path confirmed: {rel_protected}")
    print(f" Allowed path confirmed: {rel_allowed}")

    # Step 3: Simulate Step C2 - Allowed Change
    print("\n[Step 3] Simulating Step C2: Intentionally making an ALLOWED change...")
    with open(allowed_file, "w", encoding="utf-8") as f:
        f.write("Valid business logic content in allowed file.")

    c2_decision = engine.evaluate_changes([rel_allowed])
    print(f" ApprovalEngine evaluation for '{rel_allowed}': {c2_decision.value}")
    assert c2_decision == PolicyDecision.AUTO_APPROVE, "Allowed change must receive AUTO_APPROVE"
    logger.log("c2_allowed_change_verified", {"file": rel_allowed, "decision": c2_decision.value})
    print(" PASS: Safe change was accepted as expected.")

    # Step 4: Simulate Step C3 & C4 - Unauthorized Change
    print("\n[Step 4] Simulating Step C3 & C4: Attempting UNAUTHORIZED change to protected path...")
    tamper_content = "MALICIOUS_TAMPER_CONTENT: ATTEMPTED UNAUTHORIZED OVERWRITE"
    with open(protected_file, "w", encoding="utf-8") as f:
        f.write(tamper_content)
    print(f" Written unauthorized content to '{rel_protected}'")

    # Step 5: Verify strictly BLOCKED and audit recorded
    print("\n[Step 5] Verifying ApprovalEngine strictly BLOCKS the unauthorized modification...")
    c3_decision = engine.evaluate_changes([rel_protected])
    print(f" ApprovalEngine evaluation for '{rel_protected}': {c3_decision.value}")
    assert c3_decision == PolicyDecision.REJECT, "Tampered protected file must receive REJECT"
    logger.log("policy_rejection", {"violating_files": [rel_protected], "decision": c3_decision.value})
    print(" PASS: Dangerous modification strictly BLOCKED.")

    # Step 6: Verify Step C5 & C7 - Revert to clean Git checkpoint
    print("\n[Step 6] Reverting workspace to clean Git checkpoint and verifying integrity...")
    # Revert protected file back to HEAD
    subprocess.run(
        ["git", "checkout", "HEAD", "--", rel_protected],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    # Clean up test allowed file
    if os.path.exists(allowed_file):
        os.remove(allowed_file)

    # Verify content restored
    with open(protected_file, "r", encoding="utf-8") as f:
        restored_content = f.read().strip()
    print(f" Protected file content after revert: '{restored_content}'")
    assert restored_content == baseline_content, "Protected file content must match baseline"

    # Verify git status is clean for protected file
    status_res = subprocess.run(
        ["git", "status", "--porcelain", rel_protected],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
    )
    assert status_res.stdout.strip() == "", "Protected file must show no uncommitted changes"
    print(" PASS: Clean Git checkpoint restored and integrity verified.")

    logger.log("proof_completed", {"status": "SUCCESS", "checkpoint": checkpoint_sha})

    print("\n==================================================")
    print("       PHASE C: SANDBOX PROOF SUCCESSFUL")
    print("==================================================")

    return {
        "status": "SUCCESS",
        "checkpoint": checkpoint_sha,
        "c2_decision": c2_decision.value,
        "c3_decision": c3_decision.value,
        "protected_intact": True,
    }


if __name__ == "__main__":
    result = run_sandbox_proof()
    print(f"\nFinal Proof Summary: {json.dumps(result, indent=2)}")
