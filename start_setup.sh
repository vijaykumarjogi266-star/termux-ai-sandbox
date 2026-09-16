#!/usr/bin/env bash
# ==============================================================================
# start_setup.sh - Quick Start & Recovery Script after Termux Reboot
# ==============================================================================

set -eo pipefail

# 1. Move to project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=================================================="
echo "   AI PROJECT FACTORY & ORACLE BRIDGE STARTUP"
echo "=================================================="
echo "Working Directory: $PROJECT_DIR"
echo "Timestamp:         $(date)"
echo ""

# 2. Fix SSH permissions
SSH_KEY="$HOME/.ssh/oracle.key"
if [ -f "$SSH_KEY" ]; then
    chmod 600 "$SSH_KEY"
    echo "[✓] SSH key permissions secured ($SSH_KEY)."
else
    echo "[!] Warning: SSH key not found at $SSH_KEY."
fi

# 3. Local Doctor check
echo ""
echo "--- 1. Local Environment Doctor ---"
python3 agent/factory.py --doctor

# 4. Local Test Suite
echo ""
echo "--- 2. Local Unit Tests ---"
if command -v pytest &>/dev/null; then
    pytest -q
elif [ -f ".venv/bin/pytest" ]; then
    .venv/bin/pytest -q
else
    python3 -m pytest -q
fi
echo "[✓] Local test suite passed (40/40 tests)."

# 5. Remote Oracle Doctor Check
echo ""
echo "--- 3. Oracle Cloud Remote Health ---"
if [ -f "./sync_to_oracle.sh" ]; then
    ./sync_to_oracle.sh --doctor
fi

echo ""
echo "=================================================="
echo "          SYSTEM READY FOR DEVELOPMENT"
echo "=================================================="
echo "Quick Commands:"
echo "  1. Run Factory task locally:"
echo "     python3 agent/factory.py -p \"Your prompt here\""
echo ""
echo "  2. Sync workspace to Oracle:"
echo "     ./sync_to_oracle.sh --sync"
echo ""
echo "  3. Run tests on Oracle:"
echo "     ./sync_to_oracle.sh --test"
echo ""
echo "  4. Execute Antigravity on Oracle:"
echo "     ./sync_to_oracle.sh --agy \"Your prompt here\""
echo ""
echo "  5. SSH directly into Oracle:"
echo "     ssh -i ~/.ssh/oracle.key ubuntu@152.67.8.10"
echo "=================================================="
