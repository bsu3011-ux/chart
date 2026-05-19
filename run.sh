#!/bin/bash
# 서버 자동 재시작 루프 — 크래시 시 3초 후 자동 복구
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# .env 파일이 있으면 환경변수 로드 (git에 포함 안 됨)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

while true; do
    python3 server.py >> "$SCRIPT_DIR/server.log" 2>&1
    echo "[$(date)] 서버 재시작..." >> "$SCRIPT_DIR/server.log"
    sleep 3
done
