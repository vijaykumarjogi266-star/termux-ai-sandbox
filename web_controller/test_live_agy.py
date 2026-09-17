#!/usr/bin/env python3
"""
End-to-end test executing a prompt via AGY CLI through the web controller.
"""

import json
import time
import socket
import urllib.request
from threading import Thread
from server import ReusableThreadingServer, ControllerHTTPHandler, task_manager


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run_e2e_test():
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    server_inst = ReusableThreadingServer(("127.0.0.1", port), ControllerHTTPHandler)
    server_thread = Thread(target=server_inst.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.2)

    print(f"[TEST] Server started on {base_url}")

    # Start a real prompt via POST /api/task
    prompt = "Respond with exact word: PONG_TEST_SUCCESS"
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/task",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        print(f"[TEST] Task submitted: {res_data}")
        task_id = res_data["taskId"]

    # Poll status and output until completed
    max_wait = 45  # seconds
    start_t = time.time()
    offset = 0
    final_output = ""

    while time.time() - start_t < max_wait:
        time.sleep(1)
        req_status = urllib.request.Request(f"{base_url}/api/task/status?offset={offset}")
        with urllib.request.urlopen(req_status) as resp:
            status_data = json.loads(resp.read().decode("utf-8"))
            if status_data.get("output"):
                final_output += status_data["output"]
                offset = status_data["offset"]
                print(f"[TEST] Chunk received ({len(status_data['output'])} chars)")

            print(f"[TEST] Current status: {status_data['status']}, duration: {status_data['duration']}s")
            if status_data["status"] in ("completed", "failed", "stopped"):
                break

    server_inst.shutdown()
    server_inst.server_close()

    print(f"[TEST] Final Status: {status_data['status']}")
    print(f"[TEST] Final Output:\n{final_output.strip()}")
    assert "PONG_TEST_SUCCESS" in final_output, f"Expected PONG_TEST_SUCCESS in output, got: {final_output}"
    assert status_data["status"] == "completed", f"Expected completed status, got: {status_data['status']}"
    print("[TEST] End-to-end AGY test PASSED!")


if __name__ == "__main__":
    run_e2e_test()
