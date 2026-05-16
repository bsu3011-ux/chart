#!/bin/bash
# ─────────────────────────────────────────────
#  allersafe 로컬 개발 서버 (포트 8000)
# ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

export PORT="${PORT:-8000}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"

echo "🚀 allersafe 개발 서버 — http://localhost:$PORT"
echo "   중단: Ctrl+C"
echo ""

while true; do
    python3 server.py 2>&1 | tee -a "$SCRIPT_DIR/server.log"
    echo "[$(date '+%H:%M:%S')] 서버 종료 → 2초 후 재시작..." | tee -a "$SCRIPT_DIR/server.log"
    sleep 2
done
