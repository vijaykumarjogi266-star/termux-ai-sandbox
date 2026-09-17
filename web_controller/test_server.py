#!/usr/bin/env python3
"""
Test suite for AGY Web Controller Scaffold.
Tests security validations, HTTP endpoints, static asset serving,
and AGY CLI execution mechanics.
"""

import os
import sys
import time
import json
import socket
import unittest
import urllib.request
import urllib.error
from threading import Thread
from pathlib import Path

import server
from server import TaskManager, ReusableThreadingServer, ControllerHTTPHandler, FORBIDDEN_PATHS


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestTaskManagerSafety(unittest.TestCase):
    def setUp(self):
        self.tm = TaskManager()

    def test_reject_empty_prompt(self):
        res = self.tm.start_task("")
        self.assertIn("error", res)
        self.assertEqual(res["code"], 400)

        res_ws = self.tm.start_task("   \n\t  ")
        self.assertIn("error", res_ws)
        self.assertEqual(res_ws["code"], 400)

    def test_reject_null_bytes_in_prompt(self):
        res = self.tm.start_task("hello\x00world")
        self.assertIn("error", res)
        self.assertEqual(res["code"], 400)
        self.assertIn("null bytes", res["error"])

    def test_reject_oversized_prompt(self):
        oversized = "a" * (server.MAX_PROMPT_LENGTH + 10)
        res = self.tm.start_task(oversized)
        self.assertIn("error", res)
        self.assertEqual(res["code"], 400)
        self.assertIn("exceeds maximum allowed limit", res["error"])

    def test_forbidden_algolab_protection(self):
        for forbidden in FORBIDDEN_PATHS:
            res = self.tm.start_task("test prompt", working_dir=str(forbidden))
            self.assertIn("error", res)
            self.assertEqual(res["code"], 403)
            self.assertIn("strictly prohibited", res["error"])

            subpath = forbidden / "src"
            res_sub = self.tm.start_task("test prompt", working_dir=str(subpath))
            self.assertIn("error", res_sub)
            self.assertEqual(res_sub["code"], 403)

    def test_safe_invocation_no_shell(self):
        """Verify that task execution uses a direct list and does not pass shell=True."""
        import inspect
        source = inspect.getsource(self.tm._run_task_thread)
        self.assertIn("subprocess.Popen(", source)
        self.assertNotIn("shell=True", source)
        self.assertIn("cmd = [self.agy_path, \"--print\"", source)


class TestHTTPServerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = find_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server = ReusableThreadingServer(("127.0.0.1", cls.port), ControllerHTTPHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read(), response.headers

    def _post(self, path, data):
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_health_check_endpoint(self):
        status, body, headers = self._get("/api/health")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertIn("agy_path", data)
        self.assertIn("workspace", data)

    def test_ui_index_contains_required_elements(self):
        status, body, headers = self._get("/")
        self.assertEqual(status, 200)
        content = body.decode("utf-8")
        # Prompt box
        self.assertIn('id="prompt-input"', content)
        # Start Task button
        self.assertIn('id="start-btn"', content)
        self.assertIn("Start Task", content)
        # Output / status area
        self.assertIn('id="output-console"', content)
        self.assertIn('id="status-badge"', content)

    def test_static_assets_served(self):
        status_css, body_css, _ = self._get("/style.css")
        self.assertEqual(status_css, 200)
        self.assertIn(b"--bg-main", body_css)

        status_js, body_js, _ = self._get("/app.js")
        self.assertEqual(status_js, 200)
        self.assertIn(b"startTask", body_js)

    def test_initial_status_idle(self):
        status, body, _ = self._get("/api/task/status")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "idle")

    def test_start_task_validation_error(self):
        status, data = self._post("/api/task", {"prompt": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_forbidden_directory_error(self):
        status, data = self._post("/api/task", {"prompt": "test", "working_dir": "/home/ubuntu/algolab"})
        self.assertEqual(status, 403)
        self.assertIn("strictly prohibited", data["error"])

    def test_stop_task_when_idle(self):
        status, data = self._post("/api/task/stop", {})
        self.assertEqual(status, 200)
        self.assertFalse(data.get("stopped"))


if __name__ == "__main__":
    unittest.main()
