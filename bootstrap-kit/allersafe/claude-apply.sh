#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Claude 자동 반영 스크립트 (allersafe)
#  Claude 가 파일을 수정한 직후 호출.
#  사용법:
#    bash claude-apply.sh            # 기본 포트 5001
#    bash claude-apply.sh 5002       # 포트 지정
# ─────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-${PORT:-5001}}"
cd "$SCRIPT_DIR"

# ── 1. Python 구문 검사 ──────────────────────────────────────
echo "[1/3] 구문 검사..."
PY_FILES=$(find . -maxdepth 2 -name "*.py" -not -path "./venv/*" -not -path "./__pycache__/*")
ok=1
for f in $PY_FILES; do
    if python3 -c "compile(open('$f').read(), '$f', 'exec')" 2>&1; then
        echo "  ✓ $f"
    else
        echo "  ✗ $f"
        ok=0
    fi
done
[ $ok -eq 1 ] || { echo "❌ 구문 오류. 서버 재시작 취소."; exit 1; }

# ── 2. 서버 교체 ──────────────────────────────────────────────
echo "[2/3] 서버 교체 (포트 $PORT)..."
fuser -k "${PORT}/tcp" 2>/dev/null && sleep 1 || true
nohup python3 "$SCRIPT_DIR/server.py" >> "$SCRIPT_DIR/server.log" 2>&1 &
echo "  PID: $!"

# ── 3. 헬스체크 ───────────────────────────────────────────────
echo "[3/3] 헬스체크..."
for i in $(seq 1 10); do
    sleep 1
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/api/health" 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ]; then
        echo ""
        echo "✅ 반영 완료! http://localhost:${PORT}"
        exit 0
    fi
done

echo "⚠️  서버 응답 없음. tail -30 $SCRIPT_DIR/server.log"
exit 1
