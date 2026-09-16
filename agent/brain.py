"""
Phase C Brain / Project Planner
Translates high-level project goals and specifications into decomposed,
governance-compliant execution steps, and emits task files to the inbox.
"""

import os
import uuid
import datetime
from typing import List, Optional

from agent.policy import ApprovalEngine, PolicyDecision


class Brain:
    """
    Project Planner that decomposes high-level project requirements into
    executable steps, validates them against governance policy, and outputs
    task files into the orchestrator inbox.
    """

    def __init__(
        self,
        workspace_dir: str = "/root/sandbox",
        inbox_dir: Optional[str] = None,
        approval_engine: Optional[ApprovalEngine] = None,
    ):
        self.workspace_dir = workspace_dir
        self.inbox_dir = inbox_dir or os.path.join(workspace_dir, "inbox")
        os.makedirs(self.inbox_dir, exist_ok=True)
        self.approval_engine = approval_engine or ApprovalEngine()

    def decompose_project(
        self,
        project_name: str,
        objective: str,
        target_files: List[str],
    ) -> List[str]:
        """
        Decompose a project objective into structured, discrete execution steps.
        """
        files_summary = ", ".join(target_files) if target_files else "designated project files"
        steps = [
            f"Step 1: Initialize workspace and scaffold target files ({files_summary}) for project '{project_name}'.",
            f"Step 2: Implement core functionality for '{project_name}' meeting objective: {objective}.",
            f"Step 3: Create deterministic test suite verifying functionality and edge cases.",
            f"Step 4: Execute test suite and verify system stability for '{project_name}'.",
        ]
        return steps

    def validate_plan(self, target_files: List[str]) -> PolicyDecision:
        """
        Pre-validate target files against governance rules before queueing.
        """
        return self.approval_engine.evaluate_changes(target_files)

    def create_and_queue_task(
        self,
        project_name: str,
        objective: str,
        target_files: List[str],
        custom_steps: Optional[List[str]] = None,
    ) -> str:
        """
        Validate plan against policy and write the task to the inbox folder as a .txt file.
        Returns the absolute path to the generated file.
        """
        decision = self.validate_plan(target_files)
        if decision == PolicyDecision.REJECT:
            raise ValueError(
                f"Plan rejected by governance policy: target files {target_files} violate policy."
            )

        steps = custom_steps or self.decompose_project(project_name, objective, target_files)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in project_name.lower())
        filename = f"task_{safe_name}_{timestamp}_{uuid.uuid4().hex[:6]}.txt"
        file_path = os.path.join(self.inbox_dir, filename)

        content = "\n\n".join(steps) + "\n"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return file_path
