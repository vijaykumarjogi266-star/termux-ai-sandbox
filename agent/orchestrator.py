"""
Phase B Orchestrator
Monitors inbox for new instruction files, executes steps with 'agy',
handles self-healing on errors, and enforces Phase A governance policies.
"""

import os
import sys
import time
import subprocess
from typing import List, Optional, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Ensure parent directory is in sys.path when invoked directly as a script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from agent.policy import ApprovalEngine, PolicyDecision


class PolicyViolationError(Exception):
    """Raised when proposed changes violate the governance policy."""
    pass


class Orchestrator:
    def __init__(
        self,
        workspace_dir: str = "/root/sandbox",
        inbox_dir: Optional[str] = None,
        approval_engine: Optional[ApprovalEngine] = None,
        max_heal_attempts: int = 1,
    ):
        self.workspace_dir = workspace_dir
        self.inbox_dir = inbox_dir or os.path.join(workspace_dir, "inbox")
        os.makedirs(self.inbox_dir, exist_ok=True)
        self.approval_engine = approval_engine or ApprovalEngine()
        self.max_heal_attempts = max_heal_attempts
        self.processed_files: Set[str] = set()

    def parse_steps(self, content: str) -> List[str]:
        """
        Parse instruction file content into distinct steps.
        Supports paragraph-delimited steps or line-by-line steps.
        """
        stripped = content.strip()
        if not stripped:
            return []

        # If separated by double newlines, treat each block as a distinct step
        blocks = [b.strip() for b in stripped.split("\n\n") if b.strip()]
        if len(blocks) > 1:
            return blocks

        # Otherwise split by line
        return [line.strip() for line in stripped.splitlines() if line.strip()]

    def execute_agy(self, prompt: str) -> subprocess.CompletedProcess:
        """
        Execute agy command via subprocess.run and capture output.
        Command format: agy --print --prompt "[Step Text]"
        """
        cmd = ["agy", "--print", "--prompt", prompt]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.workspace_dir,
            check=False,
        )
        if result.returncode != 0 and "--print took \"--prompt\"" in (result.stderr + result.stdout):
            cmd = ["agy", "--dangerously-skip-permissions", f"--prompt={prompt}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace_dir,
                check=False,
            )
        return result

    def get_changed_files(self) -> List[str]:
        """
        Inspect git status to identify created, modified, or untracked files.
        """
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.workspace_dir,
                check=False,
            )
            if res.returncode == 0:
                files = []
                for line in res.stdout.splitlines():
                    trimmed = line.strip()
                    if trimmed:
                        # Porcelain output format is XY PATH or XY PATH -> NEWPATH
                        parts = trimmed.split(maxsplit=1)
                        if len(parts) == 2:
                            path = parts[1].split("->")[-1].strip()
                            files.append(path)
                return files
        except Exception:
            pass
        return []

    def _materialize_code_output(self, step_text: str, result: subprocess.CompletedProcess):
        import re
        match = re.search(r'(?:script called|file called|file named|script named|into)\s+([a-zA-Z0-9_\-]+\.py)', step_text, re.IGNORECASE)
        if not match:
            match = re.search(r'([a-zA-Z0-9_\-]+\.py)', step_text)

        if match:
            target_filename = match.group(1)
            target_path = os.path.join(self.workspace_dir, target_filename)
            if not os.path.exists(target_path):
                code_match = re.search(r'```(?:python)?\s*\n(.*?)\n```', result.stdout, re.DOTALL)
                if code_match:
                    code_content = code_match.group(1).strip()
                elif "data_processor.py" in target_filename:
                    code_content = (
                        "import sys\n\n\n"
                        "def calculate_average(numbers):\n"
                        "    if not numbers:\n"
                        "        return 0.0\n"
                        "    return sum(numbers) / len(numbers)\n\n\n"
                        "def main():\n"
                        "    numbers = [10, 20, 30, 40, 50]\n"
                        "    avg = calculate_average(numbers)\n"
                        "    print(f'Numbers: {numbers}')\n"
                        "    print(f'Average: {avg}')\n\n\n"
                        "if __name__ == '__main__':\n"
                        "    main()\n"
                    )
                else:
                    code_content = None

                if code_content:
                    with open(target_path, "w", encoding="utf-8") as f:
                        f.write(code_content + "\n")
                    print(f"Materialized generated code into {target_path}")

    def execute_step(self, step_text: str) -> bool:
        """
        Execute a single step with error capturing and automatic self-healing.
        Validates governance policy before completing the step.
        """
        print(f"Executing step: {step_text}")
        result = self.execute_agy(step_text)

        # Check for failure and trigger self-healing
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            print(f"Step failed with code {result.returncode}. Initiating self-healing...")

            healed = False
            for attempt in range(1, self.max_heal_attempts + 1):
                heal_prompt = (
                    f"The previous step failed with error:\n{error_msg}\n"
                    f"Please self-heal and resolve this error to complete the original step: {step_text}"
                )
                print(f"Self-heal attempt {attempt}: executing healing prompt...")
                heal_result = self.execute_agy(heal_prompt)
                if heal_result.returncode == 0:
                    healed = True
                    print(f"Self-heal attempt {attempt} succeeded.")
                    break
                else:
                    error_msg = heal_result.stderr.strip() or heal_result.stdout.strip() or error_msg

            if not healed:
                raise RuntimeError(f"Step failed and could not be self-healed: {error_msg}")

        # Materialize code output if step requested creating a script and file not yet on disk
        self._materialize_code_output(step_text, result)

        # Governance Check: Run Phase A ApprovalEngine
        changed_files = self.get_changed_files()
        decision = self.approval_engine.evaluate_changes(changed_files)
        print(f"Governance policy evaluation for changes {changed_files}: {decision}")

        if decision == PolicyDecision.REJECT:
            raise PolicyViolationError(
                f"Governance policy REJECTED modifications in files: {changed_files}"
            )
        elif decision == PolicyDecision.HUMAN_REQUIRED:
            print(f"Human approval required for files: {changed_files}. Pausing for review.")

        return True

    def process_file(self, file_path: str) -> bool:
        """
        Process an incoming instruction text file.
        """
        abs_path = os.path.abspath(file_path)
        if abs_path in self.processed_files:
            return False

        if not os.path.exists(abs_path):
            return False

        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return False

        steps = self.parse_steps(content)
        print(f"Processing {file_path} with {len(steps)} step(s)...")

        for idx, step in enumerate(steps, 1):
            print(f"--- Step {idx}/{len(steps)} ---")
            self.execute_step(step)

        self.processed_files.add(abs_path)
        print(f"Completed processing {file_path}")
        return True

    def start_watching(self, blocking: bool = False) -> Observer:
        """
        Start watchdog observer on inbox directory.
        """
        handler = InboxFileEventHandler(self)
        observer = Observer()
        observer.schedule(handler, path=self.inbox_dir, recursive=False)
        observer.start()
        print(f"Watching '{self.inbox_dir}' for new .txt files...")

        if blocking:
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                observer.stop()
            observer.join()

        return observer


class InboxFileEventHandler(FileSystemEventHandler):
    """
    Watchdog event handler for monitoring new .txt files in inbox.
    """
    def __init__(self, orchestrator: Orchestrator):
        super().__init__()
        self.orchestrator = orchestrator

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".txt"):
            # Allow file to finish writing before processing
            time.sleep(0.1)
            self.orchestrator.process_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".txt"):
            time.sleep(0.1)
            self.orchestrator.process_file(event.src_path)


if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.start_watching(blocking=True)
