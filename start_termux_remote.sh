#!/usr/bin/env bash
# ==============================================================================
# start_termux_remote.sh
# Host Web Controller in Termux & Provide Global Remote Access
# ==============================================================================

set -eo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="${PROJECT_DIR}/web_controller"
PORT="${PORT:-8085}"
SSH_PORT="${SSH_PORT:-8022}"

# Color formatting
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}==================================================${NC}"
echo -e "${BLUE}    TERMUX LOCAL HOSTING & REMOTE ACCESS TUNNEL   ${NC}"
echo -e "${BLUE}==================================================${NC}"
echo ""

# 1. Start Web Server inside Termux
echo -e "${CYAN}[1/3] Starting Local Web Controller in Termux on port ${PORT}...${NC}"
pkill -f "server.py ${PORT}" 2>/dev/null || true

nohup python3 "${WEB_DIR}/server.py" "${PORT}" "0.0.0.0" > /tmp/termux_web_server.log 2>&1 &
sleep 1

if curl -s "http://127.0.0.1:${PORT}/api/health" | grep -q "ok"; then
    echo -e "${GREEN}[✓] Termux Web Controller running at: http://localhost:${PORT}${NC}"
else
    echo -e "${YELLOW}[!] Warning: Web Controller status check pending. Log: /tmp/termux_web_server.log${NC}"
fi

# 2. Start SSH Daemon in Termux
echo ""
echo -e "${CYAN}[2/3] Starting Termux SSH Daemon (sshd) on port ${SSH_PORT}...${NC}"
pkill sshd 2>/dev/null || true
if command -v sshd &>/dev/null; then
    sshd -p "${SSH_PORT}" 2>/dev/null || true
    echo -e "${GREEN}[✓] Termux SSH Daemon active on port ${SSH_PORT}.${NC}"
else
    echo -e "${YELLOW}[!] sshd binary not installed. Install via: pkg install openssh${NC}"
fi

# 3. Remote Access Options
echo ""
echo -e "${CYAN}[3/3] Global Remote Access Methods:${NC}"
echo -e "${GREEN}--------------------------------------------------${NC}"
echo -e "A. Local Wi-Fi Browser Access:"
echo -e "   http://localhost:${PORT}"
echo -e "   http://$(hostname -I | awk '{print $1}'):${PORT}"
echo ""
echo -e "B. Worldwide HTTPS Tunnel (Serveo):"
echo -e "   Run this command in Termux to get a global HTTPS link:"
echo -e "   ${YELLOW}ssh -R 80:localhost:${PORT} serveo.net${NC}"
echo ""
echo -e "C. Worldwide Remote SSH Terminal Tunnel:"
echo -e "   Run this command in Termux to tunnel your terminal:"
echo -e "   ${YELLOW}ssh -R 2222:localhost:${SSH_PORT} serveo.net${NC}"
echo -e "${GREEN}--------------------------------------------------${NC}"
