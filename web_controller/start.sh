#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-${PORT:-8080}}"
HOST="${HOST:-127.0.0.1}"

echo "Starting AGY Web Controller on http://${HOST}:${PORT}..."
exec python3 "${DIR}/server.py" "${PORT}" "${HOST}"
