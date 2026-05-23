#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
pkill -f 'python3 server.py' 2>/dev/null
pkill -f 'bash run.sh' 2>/dev/null
sleep 1
nohup bash run.sh >> "$SCRIPT_DIR/run.log" 2>&1 &
echo "Stock-bot started: $!"
