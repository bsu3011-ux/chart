#!/bin/bash
# ─────────────────────────────────────────────
#  allersafe 프로덕션 자동 재기동 루프 (포트 8000)
#  Oracle VM 에서 nohup 으로 백그라운드 실행:
#    nohup bash run.sh > run.log 2>&1 &
# ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

export PORT="${PORT:-8000}"
# DEPLOY_SECRET 은 ~/.bashrc 또는 .env 에서 export 하길 권장

while true; do
    python3 server.py >> "$SCRIPT_DIR/server.log" 2>&1
    echo "[$(date)] allersafe 재시작..." >> "$SCRIPT_DIR/server.log"
    sleep 3
done
