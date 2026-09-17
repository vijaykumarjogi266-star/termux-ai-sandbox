import subprocess
import sys
import os

def main():
    cmd = [sys.executable, "/root/sandbox/web_controller/server.py", "8085", "0.0.0.0"]
    log_file = open("/tmp/web_server_daemon.log", "a", encoding="utf-8")
    p = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(f"Web server daemon started with PID {p.pid}")

if __name__ == "__main__":
    main()
