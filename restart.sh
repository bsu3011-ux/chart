#!/bin/bash
cd /home/ubuntu/stock-bot
pkill -f 'python3 server.py' 2>/dev/null
pkill -f 'bash run.sh' 2>/dev/null
sleep 1
nohup bash run.sh >> /home/ubuntu/stock-bot/run.log 2>&1 &
echo "Stock-bot started: $!"
