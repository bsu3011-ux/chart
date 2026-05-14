#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Claude 자동 반영 스크립트
#  Claude 가 파일을 수정한 직후 이 스크립트를 실행한다.
#
#  실행 결과:
#    1. 구문 검사 (실패 시 서버 죽이지 않고 오류만 출력)
#    2. 서버 프로세스 교체 (기존 pkill → 새 프로세스 시작)
#    3. 헬스체크 (5번 재시도)
#
#  사용법:
#    bash claude-apply.sh            # 기본 (포트 5000)
#    bash claude-apply.sh 8080       # 포트 지정
# ─────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-5000}"

cd "$SCRIPT_DIR"

# ── 1. Python 구문 검사 ────────────────────────────────────────
echo "[1/3] 구문 검사..."
if ! python3 -c "
import sys, importlib.util, traceback
files = ['server.py', 'multi_market_bot_v4.py', 'crypto_data.py']
ok = True
for f in files:
    try:
        spec = importlib.util.spec_from_file_location('_chk', f)
        mod  = importlib.util.module_from_spec(spec)
        # compile 만 (실행 X)
        with open(f) as fh:
            compile(fh.read(), f, 'exec')
        print(f'  ✓ {f}')
    except SyntaxError as e:
        print(f'  ✗ {f}: {e}', file=sys.stderr)
        ok = False
sys.exit(0 if ok else 1)
" 2>&1; then
    echo "❌ 구문 오류 발견. 서버 재시작 취소."
    exit 1
fi

# ── 2. 서버 교체 ──────────────────────────────────────────────
echo "[2/3] 서버 교체..."

# 기존 프로세스 정리
fuser -k "${PORT}/tcp" 2>/dev/null && sleep 1 || true
pkill -f "python3 server.py" 2>/dev/null && sleep 1 || true

# 백그라운드로 새 서버 기동 (로그 추가)
nohup python3 "$SCRIPT_DIR/server.py" >> "$SCRIPT_DIR/server.log" 2>&1 &
NEW_PID=$!
echo "  PID: $NEW_PID"

# ── 3. 헬스체크 ───────────────────────────────────────────────
echo "[3/3] 헬스체크..."
MAX=10
for i in $(seq 1 $MAX); do
    sleep 1
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/" 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ]; then
        echo ""
        echo "✅ 반영 완료! http://localhost:${PORT}"
        echo "   (브라우저에서 Ctrl+Shift+R 로 강력 새로고침)"
        exit 0
    fi
    echo -n "  시도 $i/$MAX (HTTP $CODE)..."
done

echo ""
echo "⚠️  서버가 응답하지 않습니다. 로그 확인:"
echo "   tail -20 $SCRIPT_DIR/server.log"
exit 1
