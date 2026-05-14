#!/bin/bash
# ─────────────────────────────────────────────
#  로컬 최초 설치 스크립트
#  사용법: bash setup.sh
# ─────────────────────────────────────────────
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== 1. Python 패키지 설치 ==="
pip3 install flask flask-cors yfinance pandas numpy --break-system-packages

echo "=== 2. 디렉토리 생성 ==="
mkdir -p output static

echo "=== 3. 권한 설정 ==="
chmod +x dev.sh claude-apply.sh 2>/dev/null || true

echo ""
echo "✅ 설치 완료!"
echo ""
echo "  서버 시작:  bash dev.sh"
echo "  접속 주소:  http://localhost:5000"
echo ""
