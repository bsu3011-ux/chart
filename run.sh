#!/bin/bash
# 서버 자동 재시작 루프 — 크래시 시 3초 후 자동 복구
cd /home/ubuntu/stock-bot
while true; do
    python3 server.py >> /home/ubuntu/stock-bot/server.log 2>&1
    sleep 3
done
