# AI Project Factory: Factory Operating Procedure (FOP)

## 1. Overview
The **AI Project Factory** is a governed, autonomous system designed to execute development tasks with strict policy constraints, human oversight, and full auditability. `agent/factory.py` serves as the primary command-line entry point, routing tasks through the **Orchestrator** and **ApprovalEngine**.

---

## 2. Command-Line Usage

### 2.1 Basic Syntax
```bash
python agent/factory.py [OPTIONS] (TASK | -p "PROMPT" | -f PATH_TO_FILE)
```

### 2.2 CLI Arguments
| Argument | Short | Description | Default |
|---|---|---|---|
| `task` | (positional) | Task prompt string or path to task file | `None` |
| `--prompt` | `-p` | Direct task prompt string (mutually exclusive with `-f`) | `None` |
| `--file` | `-f` | Path to a `.txt` task file (mutually exclusive with `-p`) | `None` |
| `--workspace` | `-w` | Root workspace path | `/root/sandbox` |
| `--audit-file` | `-a` | Path to the output JSONL audit log | `<workspace>/audit.jsonl` |
| `--timeout` | `-t` | Optional execution timeout in seconds | `None` |

### 2.3 Example Commands
- **Executing an inbox task file**:
  ```bash
  python agent/factory.py inbox/task_manifest.txt
  ```
- **Executing a prompt directly**:
  ```bash
  python agent/factory.py -p "Step 1: Create data_processor.py"
  ```

---

## 3. Expected Inputs

Tasks may be provided via the command line or formatted task files:
- **Line-delimited steps**:
  ```text
  Step 1: Create sandbox/helper.py
  Step 2: Add unit tests in sandbox/test_helper.py
  ```
- **Paragraph-delimited steps**:
  ```text
  Scaffold the utility module in sandbox/utils.py with helper routines.

  Create comprehensive tests and execute them.
  ```

---

## 4. Machine-Readable States & Exit Codes

`factory.py` guarantees that the final line of standard output is one of the following states:

| State | Exit Code | Description |
|---|---|---|
| `PASS` | `0` | All steps executed, self-healed (if needed), and passed governance checks. |
| `REJECT` | `1` | Task attempted to modify protected files or files outside allowed boundaries. |
| `HUMAN_REQUIRED` | `2` | Task required infrastructure or production changes and was not approved at the Human Gate. |
| `TIMEOUT` | `3` | Execution exceeded the configured timeout duration. |
| `FAILED` | `1` | Subprocess error occurred that could not be self-healed, or input file was missing. |

---

## 5. Safety & Governance Guarantees

### 5.1 ApprovalEngine Enforcement
- **Protected Paths**: Files such as `agent/policy.py`, `.env`, and `phase_c_proof/protected_mock.txt` are permanently protected. If any step touches them, execution halts with `REJECT`.
- **Allowed Boundaries**: File changes must remain within permitted paths (`sandbox/`, `solution.py`, `phase_c_proof/`, `data_processor.py`).

### 5.2 Human Gate (Production & Infrastructure)
- If a step modifies deployment scripts, Dockerfiles, or infrastructure definitions, the Human Gate halts execution and prompts for interactive `Y/N` confirmation.

### 5.3 Git Checkpoints
- Prior to executing any step, `factory.py` captures and records the clean Git commit SHA (`git rev-parse HEAD`), allowing full rollback upon rejection.

### 5.4 Append-Only Audit Logging (`audit.jsonl`)
- Every execution generates a structured, append-only JSONL log containing timestamps, event types, commit SHAs, policy decisions, and results.
