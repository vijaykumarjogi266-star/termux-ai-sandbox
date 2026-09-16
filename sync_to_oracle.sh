#!/usr/bin/env bash
# ==============================================================================
# sync_to_oracle.sh
# Automates synchronization, verification, and Antigravity (agy) execution
# between local environment and Oracle Cloud instance.
# ==============================================================================

set -eo pipefail

# Configuration defaults (overrideable via environment variables)
ORACLE_IP="${ORACLE_IP:-152.67.8.10}"
ORACLE_USER="${ORACLE_USER:-ubuntu}"
KEY_PATH="${ORACLE_KEY:-$HOME/.ssh/oracle.key}"
REMOTE_DEST="${ORACLE_DEST:-/home/ubuntu/termux-ai-sandbox}"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Color formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Ensure SSH key exists and has secure permissions
check_ssh_key() {
    if [[ ! -f "$KEY_PATH" ]]; then
        log_error "SSH key not found at: $KEY_PATH"
        log_info "Specify custom key via: export ORACLE_KEY=/path/to/key"
        exit 1
    fi
    chmod 600 "$KEY_PATH" 2>/dev/null || true
}

# Run SSH command with default options
run_ssh() {
    ssh -i "$KEY_PATH" \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=accept-new \
        -o ConnectTimeout=10 \
        "${ORACLE_USER}@${ORACLE_IP}" "$@"
}

# Run SCP command with default options
run_scp() {
    scp -i "$KEY_PATH" \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=accept-new \
        "$@"
}

# 1. Connection check
do_ping() {
    log_info "Testing SSH connectivity to ${ORACLE_USER}@${ORACLE_IP}..."
    check_ssh_key
    if run_ssh 'echo "ORACLE_CONNECTION_OK: host=$(hostname) time=$(date -u +%Y-%m-%dT%H:%M:%SZ)"'; then
        log_success "SSH connection established successfully."
    else
        log_error "Failed to connect to Oracle instance."
        exit 1
    fi
}

# 2. Status / Verification check
do_check() {
    log_info "Checking project status and Antigravity installation on Oracle..."
    check_ssh_key
    run_ssh bash -s << 'EOF'
set -e
echo "=== REMOTE SYSTEM & ANTIGRAVITY ==="
echo "Hostname: $(hostname)"
echo "Kernel:   $(uname -r)"
echo "Python3:  $(python3 --version 2>&1)"
echo "agy Path: $(which agy 2>/dev/null || which /usr/local/bin/agy 2>/dev/null || echo 'NOT FOUND')"
if command -v agy &>/dev/null || [ -x /usr/local/bin/agy ]; then
    AGY_BIN=$(command -v agy || echo /usr/local/bin/agy)
    echo "agy Ver:  $($AGY_BIN --version 2>&1 || true)"
else
    echo "agy: NOT FOUND"
fi

echo ""
echo "=== TARGET REPOSITORY ($HOME/termux-ai-sandbox) ==="
if [ -d "$HOME/termux-ai-sandbox" ]; then
    cd "$HOME/termux-ai-sandbox"
    echo "Location: $(pwd)"
    echo "Git Branch: $(git branch --show-current 2>/dev/null || echo 'N/A')"
    echo "Git HEAD:   $(git log -1 --oneline 2>/dev/null || echo 'N/A')"
    echo "Git Status: $(git status --short 2>/dev/null || echo 'Clean')"
    echo "Audit Log:  $(ls -lh audit.jsonl 2>/dev/null || echo 'No audit log')"
    echo "Venv:       $([ -d .venv ] && echo 'Present (.venv)' || echo 'Not present')"
else
    echo "Directory $HOME/termux-ai-sandbox does not exist."
fi

echo ""
echo "=== TARBALL BACKUPS IN $HOME ==="
ls -lh "$HOME"/ai-project-factory-migration.tar.gz "$HOME"/termux-ai-sandbox.tar.gz 2>/dev/null || echo "No tarballs found in home"
EOF
    log_success "Remote status check completed."
}

# 3. Synchronize local workspace to Oracle
do_sync() {
    log_info "Synchronizing local workspace ($LOCAL_DIR) to Oracle (${REMOTE_DEST})..."
    check_ssh_key

    TEMP_TAR="/tmp/sandbox_sync_$(date +%s).tar.gz"
    log_info "Creating clean packaging archive (excluding caches & pycache)..."

    tar -czf "$TEMP_TAR" \
        -C "$LOCAL_DIR" \
        --exclude='.pytest_cache' \
        --exclude='__pycache__' \
        --exclude='*/__pycache__' \
        --exclude='algopro' \
        --exclude='./algopro' \
        --exclude='.venv' \
        --exclude='venv' \
        .

    ARCHIVE_SIZE=$(ls -lh "$TEMP_TAR" | awk '{print $5}')
    log_info "Archive created: $TEMP_TAR ($ARCHIVE_SIZE)"

    log_info "Transferring archive to Oracle via SCP..."
    run_scp "$TEMP_TAR" "${ORACLE_USER}@${ORACLE_IP}:/tmp/sandbox_sync.tar.gz"
    rm -f "$TEMP_TAR"

    log_info "Extracting archive on Oracle into ${REMOTE_DEST}..."
    run_ssh bash -s << EOF
set -e
mkdir -p "${REMOTE_DEST}"
tar -xzf /tmp/sandbox_sync.tar.gz -C "${REMOTE_DEST}"
rm -f /tmp/sandbox_sync.tar.gz

# Ensure virtualenv exists on Oracle with pytest installed
if [ ! -d "${REMOTE_DEST}/.venv" ]; then
    echo "Creating Python virtualenv on Oracle..."
    python3 -m venv "${REMOTE_DEST}/.venv"
fi

"${REMOTE_DEST}/.venv/bin/pip" install --quiet --upgrade pip pytest
echo "Synchronization and environment setup complete."
EOF
    log_success "Workspace synchronized successfully to Oracle."
}

# 4. Run test suite on Oracle
do_test() {
    log_info "Running test suites on Oracle..."
    check_ssh_key
    run_ssh bash -s << 'EOF'
set -e
cd "$HOME/termux-ai-sandbox"

echo "=== 1. AI PROJECT FACTORY TESTS ==="
if [ -f ".venv/bin/pytest" ]; then
    .venv/bin/pytest -q
elif command -v pytest &>/dev/null; then
    pytest -q
else
    python3 -m pytest -q
fi

echo ""
echo "=== 2. ALGOPRO BASELINE GOVERNANCE SMOKE (STAGE 6: 192 TESTS) ==="
if [ -d "algopro" ]; then
    cd algopro
    if [ -f "$HOME/.local/bin/pytest" ]; then
        "$HOME/.local/bin/pytest" -q \
            --ignore=tests/unit/test_stage7_acceptance_part1.py \
            --ignore=tests/unit/test_stage7_acceptance_part2.py \
            --ignore=tests/unit/test_stage7_acceptance_part3.py
    elif [ -f "$HOME/algolab/.venv/bin/pytest" ]; then
        "$HOME/algolab/.venv/bin/pytest" -q \
            --ignore=tests/unit/test_stage7_acceptance_part1.py \
            --ignore=tests/unit/test_stage7_acceptance_part2.py \
            --ignore=tests/unit/test_stage7_acceptance_part3.py
    else
        echo "Algo Lab pytest runner not located in standard paths; skipping algopro."
    fi
fi
EOF
    log_success "Remote tests executed successfully."
}

# 5. Run Antigravity prompt or print mode on Oracle
do_agy() {
    local PROMPT_TEXT="$1"
    if [[ -z "$PROMPT_TEXT" ]]; then
        log_error "No prompt supplied for agy execution. Example: $0 --agy 'Create a health check endpoint in main.py'"
        exit 1
    fi

    log_info "Executing Antigravity (agy) prompt on Oracle..."
    check_ssh_key

    run_ssh bash -s << EOF
set -e
cd "${REMOTE_DEST}"
AGY_BIN=\$(command -v agy || echo /usr/local/bin/agy)

echo "Running: \$AGY_BIN --print \"$PROMPT_TEXT\""
\$AGY_BIN --print "$PROMPT_TEXT"
EOF
    log_success "Antigravity prompt execution finished."
}

# 6. Doctor / Full diagnostic
do_doctor() {
    log_info "Running full Oracle Antigravity Doctor diagnostics..."
    check_ssh_key
    run_ssh bash -s << 'EOF'
set -e
echo "=================================================="
echo "          ORACLE ANTIGRAVITY DOCTOR"
echo "=================================================="
echo "Date:      $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Host:      $(hostname)"
echo "User:      $(whoami)"
echo "Kernel:    $(uname -s -r -m)"
echo "Uptime:    $(uptime -p 2>/dev/null || uptime)"
echo "Memory:    $(free -h | awk '/^Mem:/ {print $3 "/" $2}')"
echo "Disk:      $(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 " used)"}')"
echo ""

echo "--- Python & Tools ---"
echo "Python3:   $(python3 --version 2>&1)"
echo "Pip:       $(pip3 --version 2>/dev/null || echo 'pip not in PATH')"
echo "Git:       $(git --version 2>&1)"
echo ""

echo "--- Antigravity (agy) ---"
AGY_PATH=$(which agy 2>/dev/null || which /usr/local/bin/agy 2>/dev/null || echo "")
if [ -n "$AGY_PATH" ]; then
    echo "agy Binary:  $AGY_PATH"
    echo "agy Version: $($AGY_PATH --version 2>&1 || true)"
    echo "agy Permissions: $(ls -l $AGY_PATH)"
    echo "Checking models backend..."
    $AGY_PATH models 2>&1 | head -n 6
else
    echo "agy Binary:  NOT FOUND"
fi
echo ""

echo "--- Workspace Verification ---"
WS="$HOME/termux-ai-sandbox"
if [ -d "$WS" ]; then
    echo "Workspace:   $WS (EXISTS)"
    cd "$WS"
    echo "Git Branch:  $(git branch --show-current 2>/dev/null || echo 'N/A')"
    echo "Git Commit:  $(git log -1 --oneline 2>/dev/null || echo 'N/A')"
    echo "Git Clean:   $(git status --porcelain 2>/dev/null | wc -l | awk '{if ($1 == 0) print "YES (Clean)"; else print "NO (" $1 " uncommitted files)"}')"
    echo "Venv:        $([ -x .venv/bin/pytest ] && echo 'OK (.venv/bin/pytest found)' || echo 'Missing or no pytest')"
    echo "Audit Log:   $([ -f audit.jsonl ] && echo "OK ($(wc -l < audit.jsonl) lines)" || echo 'Missing')"
    echo "Policy:      $([ -f agent/policy.py ] && echo 'OK (agent/policy.py found)' || echo 'Missing')"
    echo "Orchestrator:$([ -f agent/orchestrator.py ] && echo 'OK' || echo 'Missing')"
    echo "Factory:     $([ -f agent/factory.py ] && echo 'OK' || echo 'Missing')"
else
    echo "Workspace:   $WS (MISSING)"
fi
echo "=================================================="
EOF
    log_success "Doctor diagnostic completed."
}

# Help banner
show_usage() {
    cat << EOF
Usage: $0 [COMMAND] [OPTIONS]

Commands:
  --check, -c          Check Oracle environment, git status, and agy installation
  --sync, -s           Sync local project repository to Oracle (/home/ubuntu/termux-ai-sandbox)
  --test, -t           Run test suites on Oracle (Factory 40/40 + Stage 6 192/192)
  --doctor, -d         Run deep diagnostics on Oracle instance and agy configuration
  --agy, -a "PROMPT"   Execute an Antigravity prompt directly on the Oracle instance
  --ping, -p           Test SSH connectivity
  --help, -h           Show this help message

Environment overrides:
  ORACLE_IP            Oracle instance IP (default: 152.67.8.10)
  ORACLE_USER          SSH username (default: ubuntu)
  ORACLE_KEY           Private key path (default: \$HOME/.ssh/oracle.key)
  ORACLE_DEST          Destination path on Oracle (default: /home/ubuntu/termux-ai-sandbox)

Examples:
  $0 --check
  $0 --sync
  $0 --test
  $0 --doctor
  $0 --agy "Write a function to compute fibonacci numbers in fib.py"
EOF
}

# Entrypoint routing
case "${1:-}" in
    --check|-c)
        do_check
        ;;
    --sync|-s)
        do_sync
        ;;
    --test|-t)
        do_test
        ;;
    --doctor|-d)
        do_doctor
        ;;
    --agy|-a)
        shift
        do_agy "$*"
        ;;
    --ping|-p)
        do_ping
        ;;
    --help|-h|"")
        show_usage
        ;;
    *)
        log_error "Unknown argument: $1"
        show_usage
        exit 1
        ;;
esac
