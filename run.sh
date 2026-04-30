#!/bin/bash
# 서버 자동 재시작 루프 — 크래시 시 3초 후 자동 복구
cd /home/user/chart
while true; do
    python3 server.py >> /home/user/chart/server.log 2>&1
    echo "[$(date)] 서버 재시작..." >> /home/user/chart/server.log
    sleep 3
done
