#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  allersafe — Flask API 서버 (포트 5001)
  ─────────────────────────────────────────
  - 정적 파일 서빙 (static/index.html, no-cache)
  - /api/health 헬스체크
  - /deploy GitHub webhook 자동배포 (HMAC-SHA256)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os, hmac, hashlib, subprocess, threading, datetime, time
from flask import Flask, jsonify, send_from_directory, request, make_response
from flask_cors import CORS

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_DIR)
CORS(app)

# ── 자동 배포 시크릿 (환경변수 우선) ──
DEPLOY_SECRET = os.environ.get("DEPLOY_SECRET", "allersafe-deploy-change-me")


@app.route('/')
def index():
    resp = make_response(send_from_directory(STATIC_DIR, 'index.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@app.route('/api/health')
def health():
    return jsonify({
        "status": "running",
        "app": "allersafe",
        "port": int(os.environ.get("PORT", 5001)),
        "time": datetime.datetime.now().isoformat(),
    })


@app.route('/deploy', methods=['POST'])
def deploy():
    """GitHub push → 자동 git pull & 서버 재시작.
       run.sh 루프가 떠 있어야 자동 복구된다."""
    sig = request.headers.get('X-Hub-Signature-256', '')
    body = request.get_data()
    expected = 'sha256=' + hmac.new(
        DEPLOY_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 403

    def do_deploy():
        time.sleep(0.5)
        try:
            subprocess.run(['git', 'pull', 'origin', 'main'],
                           cwd=BASE_DIR, timeout=30)
        except Exception as e:
            print(f"[deploy] git pull error: {e}")
        # run.sh 가 감시하므로 pkill 만 하면 자동 재기동
        subprocess.Popen(
            f'sleep 2 && fuser -k {os.environ.get("PORT", 5001)}/tcp',
            shell=True, start_new_session=True
        )

    threading.Thread(target=do_deploy, daemon=True).start()
    return jsonify({"status": "deploying", "message": "git pull → restart"})


if __name__ == '__main__':
    port  = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n  🚀 allersafe 서버 시작 — http://localhost:{port}")
    print(f"  /api/health  — 헬스체크")
    print(f"  /deploy      — GitHub webhook\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
