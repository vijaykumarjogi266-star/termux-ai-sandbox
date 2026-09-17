# AGY Web Controller Scaffold

A minimal, secure web controller scaffold to invoke the Google Antigravity (`agy`) CLI non-interactively and stream execution output to a web UI in real-time.

## Features

- **Minimalist & Dependency-Free**: Built entirely with Python 3 standard library (`http.server`, `subprocess`, `threading`, `socketserver`).
- **Clean Web Interface**:
  - **Prompt Box**: Multi-line input with character counter and keyboard shortcut (`Ctrl` + `Enter`).
  - **Model Selector**: Optional selection of models (e.g. Gemini 3.8 Flash, Claude Sonnet, etc.).
  - **Task Controls**: "Start Task" and "Stop Task" buttons with state tracking.
  - **Output/Status Area**: Live status indicator badge (Idle, Running, Completed, Failed, Stopped), duration counter, exit code display, and auto-scrolling terminal console.
- **Safety & Process Isolation**:
  - **No Shell Injection**: Safely invokes AGY via direct argument arrays (`subprocess.Popen([agy_path, ...])`) without `shell=True`.
  - **Input Sanitization**: Enforces non-empty prompts, maximum character limits (64KB), and rejects null characters.
  - **Directory Protection**: Enforces dedicated workspace boundaries and explicitly blocks prohibited directories such as `/home/ubuntu/algolab`.
  - **Process Lifecycle Management**: Runs commands in dedicated process groups (`os.setsid`) to allow graceful `SIGTERM` / `SIGKILL` termination without leaving zombie processes.
  - **Concurrency Guard**: Enforces single active task execution to prevent runaway resource exhaustion.

## Quick Start

### Start Server
```bash
# Start on default port 8080
./start.sh

# Or specify a custom port
./start.sh 8000
```
Open your browser at `http://localhost:8080`.

## API Endpoints

- `GET /`: Serves the Web Controller UI (`index.html`).
- `GET /api/health`: Returns server status and detected AGY CLI binary path.
- `GET /api/task/status?offset=<number>`: Returns current task status and incremental output stream from `<offset>`.
- `POST /api/task`: Starts a new task with JSON payload:
  ```json
  {
    "prompt": "Your instructions for AGY",
    "model": "gemini-3.8-flash-high"
  }
  ```
- `POST /api/task/stop`: Safely terminates the currently executing task.

## Running Tests

```bash
# Unit & integration tests
python3 test_server.py

# End-to-end AGY test
python3 test_live_agy.py
```
