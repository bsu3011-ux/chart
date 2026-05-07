#!/bin/bash
# 서버 자동 재시작 루프 — 크래시 시 3초 후 자동 복구
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
while true; do
    python3 server.py >> "$SCRIPT_DIR/server.log" 2>&1
    echo "[$(date)] 서버 재시작..." >> "$SCRIPT_DIR/server.log"
    sleep 3
done
