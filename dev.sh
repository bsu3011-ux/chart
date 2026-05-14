#!/bin/bash
# ─────────────────────────────────────────────
#  로컬 개발 서버 — 크래시/재시작 자동 처리
#  사용법: bash dev.sh
#
#  Claude 가 파일을 수정한 뒤 claude-apply.sh 를 실행하면
#  이 루프가 새 코드로 서버를 다시 올린다.
# ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p output

echo "🚀 개발 서버 시작: http://localhost:5000"
echo "   중단: Ctrl+C"
echo ""

while true; do
    python3 server.py 2>&1 | tee -a "$SCRIPT_DIR/server.log"
    echo "[$(date '+%H:%M:%S')] 서버 종료 → 2초 후 재시작..." | tee -a "$SCRIPT_DIR/server.log"
    sleep 2
done
