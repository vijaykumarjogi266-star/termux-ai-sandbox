"""
Phase D Factory MVP
Unified command-line entry point for the AI Project Factory.
Routes tasks through Orchestrator & ApprovalEngine, enforces Human Gate,
manages Git checkpoints, outputs machine-readable states, and records audit trails.
"""

import os
import sys
import json
import argparse
import datetime
import subprocess
from enum import Enum
from typing import List, Optional, Callable

# Ensure parent directory is in sys.path when invoked directly as a script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from agent.policy import ApprovalEngine, PolicyDecision
from agent.orchestrator import Orchestrator, PolicyViolationError
from agent.brain import Brain


class FactoryState(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


class AuditLogger:
    """
    Appends audit events to a JSONL audit log.
    """
    def __init__(self, audit_file: str):
        self.audit_file = audit_file

    def log(self, event_type: str, details: Optional[dict] = None) -> dict:
        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details or {},
        }
        with open(self.audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry


class FactoryRunner:
    """
    Coordinates execution of tasks, policy enforcement, human gates,
    and audit logging for the AI Project Factory.
    """

    def __init__(
        self,
        workspace_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        audit_file: Optional[str] = None,
        approval_engine: Optional[ApprovalEngine] = None,
        orchestrator: Optional[Orchestrator] = None,
        input_fn: Optional[Callable[[str], str]] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.workspace_dir = workspace_dir
        self.audit_file = audit_file or os.path.join(workspace_dir, "audit.jsonl")
        self.audit_logger = AuditLogger(self.audit_file)

        # Auto-load policy config if present
        policy_config = os.path.join(workspace_dir, "factory_policy.json")
        if approval_engine is not None:
            self.approval_engine = approval_engine
        elif os.path.exists(policy_config):
            self.approval_engine = ApprovalEngine.load_from_config(policy_config)
        else:
            self.approval_engine = ApprovalEngine()

        self.orchestrator = orchestrator or Orchestrator(
            workspace_dir=self.workspace_dir,
            approval_engine=self.approval_engine,
        )
        self.brain = Brain(
            workspace_dir=self.workspace_dir,
            approval_engine=self.approval_engine,
        )
        self.input_fn = input_fn or input
        self.timeout_seconds = timeout_seconds

    def capture_checkpoint(self) -> str:
        """
        Capture and record a clean Git checkpoint before execution.
        """
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            commit_sha = res.stdout.strip() if res.returncode == 0 else "unknown"
        except Exception as e:
            commit_sha = f"checkpoint_error: {e}"

        self.audit_logger.log("git_checkpoint", {"commit_sha": commit_sha})
        return commit_sha

    def rollback_to_checkpoint(self, changed_files: Optional[List[str]] = None):
        """
        Reverts modified files back to the clean Git checkpoint.
        """
        try:
            # Revert tracked files back to HEAD
            subprocess.run(
                ["git", "checkout", "HEAD", "--", "."],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            # Remove untracked unauthorized files that were created
            if changed_files:
                for file_path in changed_files:
                    full_path = (
                        file_path
                        if os.path.isabs(file_path)
                        else os.path.join(self.workspace_dir, file_path)
                    )
                    res = subprocess.run(
                        ["git", "ls-files", "--error-unmatch", full_path],
                        cwd=self.workspace_dir,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if res.returncode != 0 and os.path.exists(full_path):
                        try:
                            os.remove(full_path)
                        except Exception:
                            pass
        except Exception as e:
            self.audit_logger.log("rollback_error", {"error": str(e)})

        self.audit_logger.log("workspace_rollback", {"reverted_files": changed_files or []})

    def check_human_gate(self, changed_files: List[str]) -> bool:
        """
        Prompt the user for Y/N approval when a change implies infrastructure or production.
        """
        self.audit_logger.log("human_gate_triggered", {"changed_files": changed_files})
        prompt_msg = (
            f"\n[HUMAN GATE] Modifications to infrastructure/production files detected:\n"
            f"Files: {changed_files}\n"
            f"Do you approve proceeding? (Y/N): "
        )
        try:
            response = self.input_fn(prompt_msg).strip().upper()
        except (EOFError, KeyboardInterrupt):
            response = "N"

        approved = response in ("Y", "YES")
        self.audit_logger.log(
            "human_gate_decision",
            {"response": response, "approved": approved, "changed_files": changed_files},
        )
        return approved

    def run_task(
        self,
        prompt: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> FactoryState:
        """
        Run a task from a prompt string or a task file path.
        Returns machine-readable FactoryState.
        """
        checkpoint_sha = self.capture_checkpoint()
        self.audit_logger.log(
            "task_started",
            {"prompt": prompt, "file_path": file_path, "checkpoint": checkpoint_sha},
        )

        try:
            # 1. Resolve steps from file or prompt
            if file_path:
                abs_path = os.path.abspath(file_path)
                if not os.path.exists(abs_path):
                    self.audit_logger.log("error", {"error": f"File not found: {file_path}"})
                    self.audit_logger.log("task_finished", {"state": FactoryState.FAILED.value})
                    return FactoryState.FAILED

                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                steps = self.orchestrator.parse_steps(content)
            elif prompt:
                steps = self.orchestrator.parse_steps(prompt)
            else:
                self.audit_logger.log("error", {"error": "Neither prompt nor file_path provided"})
                self.audit_logger.log("task_finished", {"state": FactoryState.FAILED.value})
                return FactoryState.FAILED

            if not steps:
                self.audit_logger.log("error", {"error": "No steps parsed from input"})
                self.audit_logger.log("task_finished", {"state": FactoryState.FAILED.value})
                return FactoryState.FAILED

            self.audit_logger.log("steps_parsed", {"step_count": len(steps), "steps": steps})

            # 2. Execute each step
            for idx, step in enumerate(steps, 1):
                self.audit_logger.log("step_started", {"step_index": idx, "step": step})

                # Check timeout if configured
                try:
                    # Execute via Orchestrator with configured timeout
                    result = self.orchestrator.execute_agy(step, timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired as e:
                    self.audit_logger.log("timeout_expired", {"step_index": idx, "details": str(e)})
                    self.audit_logger.log("task_finished", {"state": FactoryState.TIMEOUT.value})
                    return FactoryState.TIMEOUT

                # Handle failure and self-healing
                if result.returncode != 0:
                    error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                    self.audit_logger.log("step_error", {"step_index": idx, "error": error_msg})

                    heal_prompt = (
                        f"The previous step failed with error:\n{error_msg}\n"
                        f"Please self-heal and resolve this error to complete the original step: {step}"
                    )
                    heal_result = self.orchestrator.execute_agy(heal_prompt, timeout=self.timeout_seconds)
                    if heal_result.returncode != 0:
                        self.audit_logger.log("self_heal_failed", {"step_index": idx, "error": heal_result.stderr})
                        self.audit_logger.log("task_finished", {"state": FactoryState.FAILED.value})
                        return FactoryState.FAILED

                    self.audit_logger.log("self_heal_succeeded", {"step_index": idx})

                # Materialize code output if step requested creating a script and file not yet on disk
                self.orchestrator.materialize_code_output(step, result)

                # 3. Governance Evaluation
                changed_files = self.orchestrator.get_changed_files()
                decision = self.approval_engine.evaluate_changes(changed_files)
                self.audit_logger.log(
                    "policy_evaluation",
                    {
                        "step_index": idx,
                        "changed_files": changed_files,
                        "decision": decision.value,
                    },
                )

                if decision == PolicyDecision.REJECT:
                    self.rollback_to_checkpoint(changed_files)
                    self.audit_logger.log(
                        "policy_rejection",
                        {"step_index": idx, "violating_files": changed_files},
                    )
                    self.audit_logger.log("task_finished", {"state": FactoryState.REJECT.value})
                    return FactoryState.REJECT

                elif decision == PolicyDecision.HUMAN_REQUIRED:
                    # Enforce Human Gate
                    approved = self.check_human_gate(changed_files)
                    if not approved:
                        self.audit_logger.log("task_finished", {"state": FactoryState.HUMAN_REQUIRED.value})
                        return FactoryState.HUMAN_REQUIRED

                self.audit_logger.log("step_completed", {"step_index": idx})

            self.audit_logger.log("task_finished", {"state": FactoryState.PASS.value})
            return FactoryState.PASS

        except subprocess.TimeoutExpired:
            self.audit_logger.log("task_finished", {"state": FactoryState.TIMEOUT.value})
            return FactoryState.TIMEOUT
        except Exception as e:
            self.audit_logger.log("task_exception", {"exception": str(e)})
            self.audit_logger.log("task_finished", {"state": FactoryState.FAILED.value})
            return FactoryState.FAILED

    def generate_audit_report(self) -> dict:
        """
        Summarize events from the JSONL audit log.
        """
        stats = {
            "total_events": 0,
            "tasks_started": 0,
            "tasks_finished": 0,
            "outcomes": {
                "PASS": 0,
                "REJECT": 0,
                "HUMAN_REQUIRED": 0,
                "TIMEOUT": 0,
                "FAILED": 0,
            },
            "recent_events": [],
        }

        if os.path.exists(self.audit_file):
            try:
                with open(self.audit_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            stats["total_events"] += 1
                            event_type = entry.get("event_type")
                            details = entry.get("details", {})
                            if event_type == "task_started":
                                stats["tasks_started"] += 1
                            elif event_type == "task_finished":
                                stats["tasks_finished"] += 1
                                state = details.get("state")
                                if state in stats["outcomes"]:
                                    stats["outcomes"][state] += 1
                            stats["recent_events"].append(entry)
                        except json.JSONDecodeError:
                            continue
                stats["recent_events"] = stats["recent_events"][-10:]
            except Exception as e:
                stats["error"] = str(e)

        return stats

    def run_doctor(self) -> dict:
        """
        Diagnostic health check for the AI Project Factory environment.
        """
        checks = {}

        # 1. Workspace check
        checks["workspace_exists"] = os.path.isdir(self.workspace_dir)

        # 2. Git check
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            checks["git_initialized"] = (res.returncode == 0)
            checks["git_branch"] = res.stdout.strip() if res.returncode == 0 else "unknown"
        except Exception:
            checks["git_initialized"] = False
            checks["git_branch"] = "error"

        # 3. agy executable check
        agy_found = False
        for path in ["agy", "/root/.local/bin/agy", "/usr/bin/agy"]:
            try:
                subprocess.run([path, "--version"], capture_output=True, check=False)
                agy_found = True
                checks["agy_path"] = path
                break
            except (FileNotFoundError, PermissionError):
                pass
        checks["agy_available"] = agy_found

        # 4. Governance configuration
        checks["allowed_paths_count"] = len(self.approval_engine.allowed_paths)
        checks["protected_paths_count"] = len(self.approval_engine.protected_paths)

        # 5. Audit log check
        checks["audit_log_present"] = os.path.exists(self.audit_file)

        return checks


def main():
    parser = argparse.ArgumentParser(description="AI Project Factory MVP Entry Point")
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="Task prompt string or path to task instruction file",
    )
    parser.add_argument("-p", "--prompt", help="Direct task prompt string")
    parser.add_argument("-f", "--file", help="Path to task instruction file")

    parser.add_argument(
        "-w", "--workspace", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), help="Path to workspace directory"
    )
    parser.add_argument(
        "-a", "--audit-file", default=None, help="Path to JSONL audit log file"
    )
    parser.add_argument(
        "-t", "--timeout", type=int, default=None, help="Timeout in seconds"
    )
    parser.add_argument(
        "--report", "--status", dest="report", action="store_true", help="Display summary of audit log"
    )
    parser.add_argument(
        "--doctor", action="store_true", help="Run factory diagnostic health check"
    )
    parser.add_argument(
        "--allow", help="Comma-separated list of paths to temporarily allow"
    )

    args = parser.parse_args()

    runner = FactoryRunner(
        workspace_dir=args.workspace,
        audit_file=args.audit_file,
        timeout_seconds=args.timeout,
    )

    if args.allow:
        for p in args.allow.split(","):
            p = p.strip()
            if p:
                runner.approval_engine.add_allowed_path(p)

    if args.doctor:
        doc = runner.run_doctor()
        print("=== AI Project Factory Health Check ===")
        for k, v in doc.items():
            print(f"  {k}: {v}")
        sys.exit(0)

    if args.report:
        report = runner.generate_audit_report()
        print("=== AI Project Factory Audit Report ===")
        print(f"Total Audit Events: {report['total_events']}")
        print(f"Tasks Started:      {report['tasks_started']}")
        print(f"Tasks Finished:     {report['tasks_finished']}")
        print("Outcomes:")
        for outcome, count in report["outcomes"].items():
            print(f"  {outcome:<15}: {count}")
        sys.exit(0)

    prompt = args.prompt
    file_path = args.file

    if not prompt and not file_path:
        if args.task:
            if os.path.exists(args.task):
                file_path = args.task
            else:
                prompt = args.task
        else:
            parser.error("Must provide a task prompt or file path (e.g. -p, -f, or positional argument).")

    state = runner.run_task(prompt=prompt, file_path=file_path)

    # Machine-readable output guaranteed on final line of stdout
    print(state.value)

    # Exit code mapping
    if state == FactoryState.PASS:
        sys.exit(0)
    elif state == FactoryState.HUMAN_REQUIRED:
        sys.exit(2)
    elif state == FactoryState.TIMEOUT:
        sys.exit(3)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
