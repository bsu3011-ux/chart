# Bootstrap Kit

`chart` 의 자동배포 패턴(로컬 Edit → push → GitHub webhook → Oracle 자동 반영)을
다른 레포에 그대로 이식하기 위한 키트.

## 현재 포함된 프로젝트

| 디렉토리 | 대상 레포 | 포트 |
|---|---|---|
| `allersafe/` | `<your-org>/allersafe` | **8000** (이미 운영 중) |

---

## ⚠️ 중요 — allersafe 는 이미 8000 포트에서 운영 중

allersafe 가 이미 Oracle 8000 에서 돌고 있다면, **server.py 를 통째로 덮어쓰면 안 됩니다.**
기존 코드를 보존하면서 **자동배포 + Claude 통합 기능만 흡수**하는 방식으로 진행하세요.

### A. "덧붙이기" 모드 (권장)

기존 allersafe 코드는 그대로 두고, 다음 파일들만 복사:

```bash
cd /path/to/allersafe

# 필수 5개 (기존 파일과 충돌 안 함)
cp /home/user/chart/bootstrap-kit/allersafe/claude-apply.sh ./
cp /home/user/chart/bootstrap-kit/allersafe/dev.sh          ./
cp /home/user/chart/bootstrap-kit/allersafe/run.sh          ./
cp /home/user/chart/bootstrap-kit/allersafe/CLAUDE.md       ./
chmod +x claude-apply.sh dev.sh run.sh

# 선택: 의존성 정의 없을 때만
[ ! -f requirements.txt ] && cp /home/user/chart/bootstrap-kit/allersafe/requirements.txt ./
```

그리고 **기존 server.py 에 `/deploy` 라우트만 추가**합니다.
`bootstrap-kit/allersafe/server.py` 의 다음 부분을 복사해서 기존 server.py 에 붙여넣으세요:

```python
import os, hmac, hashlib, subprocess, threading, time
from flask import request, jsonify

DEPLOY_SECRET = os.environ.get("DEPLOY_SECRET", "allersafe-deploy-change-me")

@app.route('/deploy', methods=['POST'])
def deploy():
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
                           cwd=os.path.dirname(os.path.abspath(__file__)),
                           timeout=30)
        except Exception as e:
            print(f"[deploy] git pull error: {e}")
        subprocess.Popen(
            f'sleep 2 && fuser -k {os.environ.get("PORT", 8000)}/tcp',
            shell=True, start_new_session=True
        )

    threading.Thread(target=do_deploy, daemon=True).start()
    return jsonify({"status": "deploying"})


@app.route('/api/health')   # 이미 있으면 생략
def health():
    return jsonify({"status": "running", "app": "allersafe",
                    "port": int(os.environ.get("PORT", 8000))})
```

> 기존 server.py 에서 포트를 하드코딩으로 쓰고 있다면 `os.environ.get("PORT", 8000)` 로 바꿔서
> 환경변수로 통일하는 게 안전합니다.

---

### B. "전면 교체" 모드 (allersafe 가 아직 비어있거나 초기 단계일 때)

```bash
rsync -a /home/user/chart/bootstrap-kit/allersafe/ /path/to/allersafe/
cd /path/to/allersafe
git add .
git commit -m "feat: 자동배포 부트스트랩 (chart 패턴 이식)"
git push origin main
```

---

## Oracle 셋업

### 이미 allersafe 가 8000 에서 운영 중인 경우 (대부분 해당)

이미 다음은 갖춰져 있을 것 — 다시 안 해도 됨:
- ✅ git clone, pip install
- ✅ OCI Security List 의 8000 개방
- ✅ iptables / firewalld 8000 통과
- ✅ 서버 프로세스 띄워둔 상태

추가로 한 번만 더 해야 하는 것:
- ⬜ `DEPLOY_SECRET` 환경변수 설정 + 서버 재기동
- ⬜ `run.sh` 가 감시하도록 프로세스 전환 (또는 systemd 등록)
- ⬜ GitHub Webhook 등록 (`http://163.192.35.70:8000/deploy`)

→ 자세한 절차는 `INSTALL_ON_ORACLE.md` §4–§7 참조 (§A 와 §3 은 이미 완료된 상태라 건너뛰면 됨).

### 처음부터 까는 경우

`INSTALL_ON_ORACLE.md` 전체를 차례대로 진행.

---

## 그 후 일상 작업

- Claude/사용자 누구든 `bash claude-apply.sh` (로컬 즉시 반영)
- `git push origin main` → webhook → Oracle 자동 반영
- Oracle SSH 다시 들어갈 일 없음
