#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 모든 run.sh / server.py 변종 완전 종료
pkill -9 -f 'python3 server.py' 2>/dev/null
pkill -9 -f 'server.py' 2>/dev/null
pkill -9 -f 'run.sh' 2>/dev/null
sleep 2

# 포트 5000 강제 해제
fuser -k 5000/tcp 2>/dev/null
sleep 1

# 단 하나의 run.sh 시작
nohup bash "$SCRIPT_DIR/run.sh" >> "$SCRIPT_DIR/run.log" 2>&1 &
echo "Stock-bot started: $!"
