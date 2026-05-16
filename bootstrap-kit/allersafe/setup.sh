#!/bin/bash
# ─────────────────────────────────────────────
#  allersafe 로컬/Oracle 최초 설치
#  사용법: bash setup.sh
# ─────────────────────────────────────────────
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== 1. Python 패키지 설치 ==="
pip3 install -r requirements.txt --break-system-packages

echo "=== 2. 디렉토리 생성 ==="
mkdir -p static output

echo "=== 3. 권한 설정 ==="
chmod +x dev.sh run.sh claude-apply.sh 2>/dev/null || true

echo ""
echo "✅ 설치 완료!"
echo ""
echo "  로컬 개발:  bash dev.sh"
echo "  Oracle 운영: nohup bash run.sh > run.log 2>&1 &"
echo "  접속 주소:  http://localhost:8000"
echo ""
echo "⚠️  배포 자동화 사용 시 DEPLOY_SECRET 환경변수를 꼭 바꾸세요:"
echo "    export DEPLOY_SECRET='your-strong-secret-here'"
echo ""
