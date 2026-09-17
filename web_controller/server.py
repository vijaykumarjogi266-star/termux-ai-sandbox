#!/usr/bin/env python3
"""
AGY Web Controller Server
A minimal, secure web controller scaffold to invoke the AGY CLI and view live status/output.
Uses standard Python library (no external dependencies required).
"""

import os
import sys
import json
import time
import uuid
import signal
import shutil
import re
import urllib.parse
from pathlib import Path
from threading import Thread, Lock
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

# Configuration defaults - bind safely to localhost for local testing
DEFAULT_HOST = os.environ.get("HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("PORT", "8080"))
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = (BASE_DIR / "static").resolve()
WORKSPACE_DIR = (BASE_DIR / "workspace").resolve()
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# Safety constraints
FORBIDDEN_PATHS = [
    Path("/home/ubuntu/algolab").resolve(),
]
MAX_PROMPT_LENGTH = 65536
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 300
MIN_TIMEOUT_SECONDS = 1
MAX_OUTPUT_BYTES = 5 * 1024 * 1024  # 5MB in-memory buffer limit
MAX_REQUEST_BODY_BYTES = 1024 * 1024  # 1MB request body limit

# Safe environment variables allowlist
SAFE_ENV_ALLOWLIST = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
}

# Sensitive variable patterns that must never be passed to AGY
SENSITIVE_ENV_PATTERNS = (
    "KEY",
    "SECRET",
    "TOKEN",
    "AUTH",
    "PASS",
    "CRED",
    "CSRF",
    "SSH",
    "AWS",
    "GITHUB",
    "PRIVATE",
    "COOKIE",
    "SIGNATURE",
    "API",
)

FIXED_AGY_PATH = os.environ.get("AGY_PATH", "/home/ubuntu/.local/bin/agy")


def find_agy_binary() -> str:
    """Locates the agy CLI binary safely through fixed absolute paths."""
    fixed_path = Path(FIXED_AGY_PATH).resolve()
    if fixed_path.is_file() and os.access(fixed_path, os.X_OK):
        return str(fixed_path)

    fallback_candidates = [
        "/usr/local/bin/agy",
        "/usr/bin/agy",
        shutil.which("agy"),
    ]
    for candidate in fallback_candidates:
        if candidate:
            resolved = Path(candidate).resolve()
            if resolved.is_file() and os.access(resolved, os.X_OK):
                return str(resolved)
    return str(fixed_path)


def get_safe_env() -> dict[str, str]:
    """
    Constructs a minimal, sanitized environment dictionary for AGY execution.
    Only non-sensitive, allowlisted variables are passed to AGY.
    """
    safe_env = {
        "PATH": "/home/ubuntu/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": str(Path.home()),
        "USER": "ubuntu",
        "LOGNAME": "ubuntu",
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "TERM": "xterm-256color",
    }
    for var in SAFE_ENV_ALLOWLIST:
        val = os.environ.get(var)
        if val is not None:
            upper_var = var.upper()
            if not any(pattern in upper_var for pattern in SENSITIVE_ENV_PATTERNS):
                safe_env[var] = val
    return safe_env


def get_descendant_pids(parent_pid: int) -> set[int]:
    """Find all descendant process IDs of a given pid."""
    descendants = set()
    to_visit = [parent_pid]
    while to_visit:
        curr = to_visit.pop()
        found = []
        children_file = Path(f"/proc/{curr}/task/{curr}/children")
        if children_file.exists():
            try:
                found = [int(p) for p in children_file.read_text().split()]
            except Exception:
                pass
        if not found:
            try:
                out = subprocess.check_output(
                    ["pgrep", "-P", str(curr)],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                found = [int(p) for p in out.strip().split() if p.isdigit()]
            except Exception:
                pass
        for p in found:
            if p not in descendants and p != parent_pid:
                descendants.add(p)
                to_visit.append(p)
    return descendants


class TaskManager:
    """Thread-safe manager for executing and tracking AGY tasks."""

    def __init__(self):
        self.lock = Lock()
        self.current_task = None
        self.task_history = []
        self.agy_path = find_agy_binary()

    def get_status(self, offset: int = 0):
        with self.lock:
            if not self.current_task:
                return {
                    "hasTask": False,
                    "status": "idle",
                    "output": "",
                    "offset": 0,
                    "totalLength": 0,
                }
            task = self.current_task
            output_slice = task["output"][offset:]
            return {
                "hasTask": True,
                "taskId": task["id"],
                "status": task["status"],
                "prompt": task["prompt"],
                "startTime": task["start_time"],
                "duration": round((task["end_time"] or time.time()) - task["start_time"], 2),
                "exitCode": task["exit_code"],
                "error": task["error"],
                "offset": offset + len(output_slice),
                "totalLength": len(task["output"]),
                "output": output_slice,
            }

    def start_task(
        self,
        prompt: str,
        model: str = None,
        working_dir: str = None,
        timeout: int = None,
    ) -> dict:
        with self.lock:
            # Enforce one active task
            if self.current_task:
                if self.current_task.get("status") in ("running", "stopping"):
                    return {"error": "A task is already running. Please wait or stop it first.", "code": 409}
                proc = self.current_task.get("process")
                if proc and proc.poll() is None:
                    return {"error": "A task is already running. Please wait or stop it first.", "code": 409}

            # Safety Validations on Prompt
            if not prompt or not isinstance(prompt, str):
                return {"error": "Prompt must be a non-empty string.", "code": 400}

            cleaned_prompt = prompt.strip()
            if not cleaned_prompt:
                return {"error": "Prompt cannot be empty or only whitespace.", "code": 400}

            if "\x00" in cleaned_prompt:
                return {"error": "Prompt contains invalid characters (null bytes).", "code": 400}

            if len(cleaned_prompt) > MAX_PROMPT_LENGTH:
                return {
                    "error": f"Prompt length exceeds maximum allowed limit ({MAX_PROMPT_LENGTH} chars).",
                    "code": 400,
                }

            # Safety Validations on Model (if provided)
            if model is not None:
                if not isinstance(model, str):
                    return {"error": "Model must be a string.", "code": 400}
                model = model.strip()
                if not model:
                    model = None
                else:
                    if len(model) > 128:
                        return {"error": "Model name exceeds maximum allowed limit (128 chars).", "code": 400}
                    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$", model):
                        return {"error": "Model name contains invalid characters.", "code": 400}

            # Working directory resolution and safety check
            # Controller workspace is strictly bound to WORKSPACE_DIR.
            # HTTP input must NEVER select or escape the controller workspace.
            workspace_resolved = WORKSPACE_DIR.resolve()
            cwd = workspace_resolved
            if working_dir:
                resolved_cwd = Path(working_dir).resolve()
                # Explicit check against forbidden directories
                for forbidden in FORBIDDEN_PATHS:
                    if resolved_cwd == forbidden or forbidden in resolved_cwd.parents:
                        return {
                            "error": f"Access to directory '{resolved_cwd}' is strictly prohibited.",
                            "code": 403,
                        }
                # Must be strictly within WORKSPACE_DIR
                try:
                    resolved_cwd.relative_to(workspace_resolved)
                except ValueError:
                    return {
                        "error": f"Access to directory '{working_dir}' is strictly prohibited. Selection or escaping of controller workspace is not allowed.",
                        "code": 403,
                    }
                if not resolved_cwd.is_dir():
                    return {"error": f"Working directory '{working_dir}' does not exist.", "code": 400}
                cwd = resolved_cwd

            # Timeout resolution
            effective_timeout = DEFAULT_TIMEOUT_SECONDS
            if timeout is not None:
                try:
                    timeout_val = int(timeout)
                    effective_timeout = max(MIN_TIMEOUT_SECONDS, min(timeout_val, MAX_TIMEOUT_SECONDS))
                except (ValueError, TypeError):
                    return {"error": "Timeout must be an integer.", "code": 400}

            task_id = str(uuid.uuid4())[:8]
            task = {
                "id": task_id,
                "prompt": cleaned_prompt,
                "status": "running",
                "start_time": time.time(),
                "end_time": None,
                "exit_code": None,
                "error": None,
                "output": "",
                "process": None,
                "pgid": None,
                "working_dir": str(cwd),
                "model": model,
                "timeout": effective_timeout,
                "timed_out": False,
            }
            self.current_task = task

        # Launch execution in background thread
        thread = Thread(target=self._run_task_thread, args=(task,), daemon=True)
        thread.start()

        return {"taskId": task_id, "status": "running"}

    def stop_current_task(self) -> dict:
        with self.lock:
            if not self.current_task or self.current_task["status"] != "running":
                return {"message": "No active task to stop.", "stopped": False}

            task = self.current_task
            task["status"] = "stopped"
            task["end_time"] = time.time()
            self._append_output(task, "\n\n[Task stopped by user]\n")

        # Terminate complete process tree safely
        self._terminate_task_process_tree(task)
        return {"message": "Task stopped successfully.", "stopped": True}

    def _terminate_task_process_tree(self, task: dict):
        """Safely terminates the complete process tree for a task."""
        proc = task.get("process")
        pgid = task.get("pgid")
        pid = proc.pid if proc else None

        descendants = set()
        if pid:
            descendants = get_descendant_pids(pid)

        # 1. Graceful SIGTERM to process group and known descendants
        if pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

        for dpid in descendants:
            try:
                os.kill(dpid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

        # 2. Brief grace period for cleanup
        grace_deadline = time.time() + 0.5
        while time.time() < grace_deadline:
            if proc and proc.poll() is not None:
                break
            time.sleep(0.05)

        # 3. Forceful SIGKILL to ensure complete termination
        if pgid:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        if pid:
            survivors = get_descendant_pids(pid)
            for spid in survivors | descendants:
                try:
                    os.kill(spid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        # 4. Reap process
        if proc:
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass

    def _handle_timeout(self, task: dict):
        """Callback invoked when hard execution timeout expires."""
        with self.lock:
            if task.get("status") != "running":
                return
            timeout_sec = task.get("timeout", DEFAULT_TIMEOUT_SECONDS)
            task["status"] = "failed"
            task["timed_out"] = True
            task["end_time"] = time.time()
            task["error"] = f"Task timed out after {timeout_sec} seconds."
            self._append_output(task, f"\n[Task timed out after {timeout_sec}s]\n")

        self._terminate_task_process_tree(task)

    def _append_output(self, task: dict, text: str):
        with self.lock:
            if len(task["output"]) + len(text) <= MAX_OUTPUT_BYTES:
                task["output"] += text
            else:
                remaining = MAX_OUTPUT_BYTES - len(task["output"])
                if remaining > 0:
                    task["output"] += text[:remaining]
                    task["output"] += "\n[Output truncated: reached max buffer limit]\n"

    def _run_task_thread(self, task: dict):
        """Worker thread to execute AGY safely using subprocess without shell invocation."""
        with self.lock:
            if task.get("status") != "running":
                return

        # Fixed executable path and argument array: shell=False
        cmd = [self.agy_path, "--print", task["prompt"], "--output-format", "text"]
        if task.get("model"):
            cmd.extend(["--model", task["model"]])

        safe_env = get_safe_env()

        try:
            # Safe process invocation:
            # 1. Direct argument array with shell=False
            # 2. setsid starts a new process group for clean tree termination
            # 3. Sanitized environment prevents exposing secrets
            proc = subprocess.Popen(
                cmd,
                cwd=task["working_dir"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,
                env=safe_env,
                shell=False,
            )

            with self.lock:
                if task["status"] != "running":
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                    return

                task["process"] = proc
                task["pgid"] = os.getpgid(proc.pid)

                # Start hard execution timeout watchdog
                timeout_sec = task.get("timeout", DEFAULT_TIMEOUT_SECONDS)
                watchdog = Thread(target=self._watchdog_thread, args=(task, timeout_sec), daemon=True)
                watchdog.start()

            # Stream output
            try:
                for line in iter(proc.stdout.readline, ""):
                    self._append_output(task, line)
            finally:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

            try:
                exit_code = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate_task_process_tree(task)
                exit_code = -1

            with self.lock:
                if task.get("timed_out"):
                    task["exit_code"] = exit_code
                    return
                # If it was stopped already, keep stopped status
                if task["status"] == "running":
                    task["exit_code"] = exit_code
                    task["end_time"] = time.time()
                    if exit_code == 0:
                        task["status"] = "completed"
                    else:
                        task["status"] = "failed"
                        task["error"] = f"Process exited with non-zero code {exit_code}"

        except FileNotFoundError:
            with self.lock:
                task["status"] = "failed"
                task["end_time"] = time.time()
                task["error"] = f"AGY binary not found at '{self.agy_path}'."
                self._append_output(task, f"\nError: AGY binary not found at '{self.agy_path}'.\n")
        except Exception as e:
            with self.lock:
                if task["status"] == "running":
                    task["status"] = "failed"
                    task["end_time"] = time.time()
                    task["error"] = str(e)
                    self._append_output(task, f"\nExecution error: {str(e)}\n")

    def _watchdog_thread(self, task: dict, timeout_seconds: float):
        """Monitors task execution time and enforces hard timeout."""
        start = task.get("start_time", time.time())
        while True:
            elapsed = time.time() - start
            if elapsed >= timeout_seconds:
                self._handle_timeout(task)
                return
            with self.lock:
                if task.get("status") != "running":
                    return
            sleep_dur = min(0.2, timeout_seconds - elapsed)
            time.sleep(sleep_dur)


# Global task manager instance
task_manager = TaskManager()


class ControllerHTTPHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for the Controller Web UI and REST API."""

    def log_message(self, format, *args):
        # Suppress routine log flooding for polling requests
        if args and "GET /api/task/status" in str(args[0]):
            return
        super().log_message(format, *args)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: str):
        if not file_path.is_file():
            self.send_error(404, "File Not Found")
            return
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {str(e)}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # Health check
        if path == "/api/health":
            self._send_json({
                "status": "ok",
                "agy_path": task_manager.agy_path,
                "workspace": str(WORKSPACE_DIR),
            })
            return

        # Task status and incremental output
        if path == "/api/task/status":
            offset = 0
            if "offset" in query:
                try:
                    offset = max(0, int(query["offset"][0]))
                except ValueError:
                    offset = 0
            status_data = task_manager.get_status(offset=offset)
            self._send_json(status_data)
            return

        # Serve UI static files
        if path == "/" or path == "/index.html":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        elif path == "/style.css":
            self._send_file(STATIC_DIR / "style.css", "text/css; charset=utf-8")
            return
        elif path == "/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        elif path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            try:
                safe_file = (STATIC_DIR / rel_path).resolve()
                if (safe_file == STATIC_DIR or STATIC_DIR in safe_file.parents) and safe_file.is_file():
                    content_type = "text/plain"
                    if safe_file.suffix == ".html":
                        content_type = "text/html; charset=utf-8"
                    elif safe_file.suffix == ".css":
                        content_type = "text/css; charset=utf-8"
                    elif safe_file.suffix == ".js":
                        content_type = "application/javascript; charset=utf-8"
                    elif safe_file.suffix in [".svg"]:
                        content_type = "image/svg+xml"
                    self._send_file(safe_file, content_type)
                    return
            except Exception:
                pass

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # Read JSON body safely
        content_length = self.headers.get("Content-Length")
        if not content_length:
            self._send_json({"error": "Missing Content-Length header"}, 400)
            return

        try:
            length = int(content_length)
            if length > MAX_REQUEST_BODY_BYTES:
                self._send_json({"error": "Payload too large"}, 413)
                return
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body) if body else {}
        except Exception as e:
            self._send_json({"error": f"Invalid JSON payload: {str(e)}"}, 400)
            return

        if not isinstance(payload, dict):
            self._send_json({"error": "JSON payload must be an object."}, 400)
            return

        # Explicitly reject arbitrary shell commands
        for cmd_key in ("command", "cmd", "sh", "shell", "exec", "bash", "script"):
            if cmd_key in payload:
                self._send_json({"error": "Arbitrary shell commands are not permitted."}, 400)
                return

        if path == "/api/task" or path == "/api/tasks":
            prompt = payload.get("prompt", "")
            model = payload.get("model", None)
            working_dir = payload.get("working_dir", None)
            timeout = payload.get("timeout", None)
            result = task_manager.start_task(
                prompt=prompt,
                model=model,
                working_dir=working_dir,
                timeout=timeout,
            )
            if "error" in result:
                self._send_json(result, result.get("code", 400))
            else:
                self._send_json(result, 201)
            return

        if path == "/api/task/stop" or path == "/api/tasks/stop":
            result = task_manager.stop_current_task()
            self._send_json(result, 200)
            return

        self.send_error(404, "Not Found")


class ReusableThreadingServer(socketserver.ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    server = ReusableThreadingServer((host, port), ControllerHTTPHandler)
    print(f"==================================================")
    print(f" AGY Web Controller Server started successfully   ")
    print(f" Access URL: http://{host}:{port}                 ")
    print(f" Workspace : {WORKSPACE_DIR}                      ")
    print(f" AGY Binary: {task_manager.agy_path}              ")
    print(f"==================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    port = DEFAULT_PORT
    host = DEFAULT_HOST
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [port] [host]")
            sys.exit(1)
    if len(sys.argv) > 2:
        host = sys.argv[2]
    run_server(host=host, port=port)
