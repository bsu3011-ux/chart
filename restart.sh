#!/bin/bash
cd /home/ubuntu/stock-bot
pkill -f 'python3 server.py' 2>/dev/null
sleep 1
nohup python3 server.py > output.log 2>&1 &
echo "Stock-bot started: $!"
