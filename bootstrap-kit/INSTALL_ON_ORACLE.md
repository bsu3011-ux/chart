# Oracle VM 1회 셋업 가이드 — allersafe

> 이 문서는 **Oracle VM 에 SSH 로 한 번만 들어가서** allersafe 자동배포를 깔기 위한 절차다.
> 이 단계만 끝나면 그 뒤로는 **`git push` 만으로 운영 반영**되고 SSH 가 더 이상 필요 없다.
>
> 작업자: SSH 가능한 사람 (사용자 본인 또는 Oracle 관리자)
> 소요 시간: 약 5~10분

---

## 시작 전 체크 — 어느 단계부터인가

allersafe 가 **이미 Oracle 8000 에서 돌고 있는 상태**라면 §A 와 §1~3 은 이미 완료된 상황이다.
다음 명령으로 현재 상태부터 점검:

```bash
ss -tlnp | grep :8000              # 무엇이 8000에 떠 있는가
curl -s http://localhost:8000/      # 응답이 정상인가
ps -ef | grep python | grep -v grep # 어떤 프로세스인가
ls ~/allersafe 2>/dev/null && cd ~/allersafe && git remote -v
```

결과에 따라 진입점이 다르다:

| 상태 | 진입점 |
|---|---|
| 8000 에 allersafe Flask 가 떠 있고 git 디렉토리도 있음 | **§4 (DEPLOY_SECRET) 부터** 시작 |
| 8000 에 떠 있지만 git 이 아니거나 다른 위치 | §1 부터 (기존 프로세스 정리 후) |
| 아무것도 없음 | §A 부터 전체 진행 |

---

## 사전 준비 (Oracle Cloud 웹 콘솔에서 1회)

### A. OCI Security List 에서 포트 8000 열기

1. Oracle Cloud Console 로그인 → Networking → Virtual Cloud Networks
2. 해당 VCN → Security Lists → Default Security List
3. **Ingress Rules → Add Ingress Rules**
   - Source CIDR: `0.0.0.0/0`
   - IP Protocol: `TCP`
   - Destination Port Range: `8000`
4. 저장

> chart 가 이미 5000 으로 동작 중이라면 8000 도 같은 방식으로 추가.

---

## SSH 단계 (Oracle VM 안에서)

### 1. 접속 & 코드 받기

```bash
ssh ubuntu@163.192.35.70    # 또는 본인 키로 접속
cd ~
git clone https://github.com/<your-org>/allersafe.git
cd allersafe
```

### 2. 의존성 설치

```bash
bash setup.sh
# → pip install flask flask-cors
```

### 3. 호스트 방화벽(iptables) 열기 — Ubuntu/Oracle Linux 공통

```bash
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || \
  sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

> firewalld 쓰는 시스템이면:
> ```bash
> sudo firewall-cmd --permanent --add-port=8000/tcp
> sudo firewall-cmd --reload
> ```

### 4. DEPLOY_SECRET 환경변수 설정

```bash
# 강력한 시크릿 생성 (예시)
SECRET=$(openssl rand -hex 32)
echo "export DEPLOY_SECRET='$SECRET'" >> ~/.bashrc
source ~/.bashrc
echo "$SECRET"
# ── 이 값을 메모해두세요. 아래 §6 의 GitHub Webhook 등록에 필요합니다.
```

### 5. 자동 재기동 루프 띄우기

```bash
cd ~/allersafe
nohup bash run.sh > run.log 2>&1 &
disown
sleep 3
curl -s http://localhost:8000/api/health
```

다음과 같이 나오면 성공:
```json
{"app":"allersafe","port":8000,"status":"running","time":"..."}
```

외부에서도 확인:
```bash
curl -s http://163.192.35.70:8000/api/health
```

### 6. systemd 등록 (선택 — 재부팅 시 자동 시작)

```bash
sudo tee /etc/systemd/system/allersafe.service > /dev/null <<'EOF'
[Unit]
Description=allersafe Flask server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/allersafe
EnvironmentFile=/home/ubuntu/allersafe/.env
ExecStart=/bin/bash /home/ubuntu/allersafe/run.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# .env 파일에 시크릿 저장
echo "DEPLOY_SECRET=$SECRET" > ~/allersafe/.env
chmod 600 ~/allersafe/.env

sudo systemctl daemon-reload
sudo systemctl enable --now allersafe
sudo systemctl status allersafe
```

기존 `nohup` 으로 돌고 있다면:
```bash
fuser -k 8000/tcp     # 기존 종료
sudo systemctl start allersafe
```

---

## GitHub 단계 (브라우저에서 1회)

### 7. Webhook 등록

1. https://github.com/<your-org>/allersafe → **Settings → Webhooks → Add webhook**
2. 다음과 같이 입력:

| 필드 | 값 |
|---|---|
| Payload URL | `http://163.192.35.70:8000/deploy` |
| Content type | `application/json` |
| Secret | §4 에서 생성한 `$SECRET` 값 |
| SSL verification | Disable (HTTP 라서) |
| Which events | **Just the `push` event** |
| Active | ✅ |

저장하면 GitHub 가 즉시 ping 을 한 번 쏘는데, 응답이 `403 invalid signature` 가 아니라 `200 deploying` 으로 와야 함.

> `403` 이 뜨면 시크릿이 일치하지 않는 것. `~/.bashrc` 의 값과 GitHub Secret 필드 값을 다시 맞추고 서버 재기동.

---

## 검증

### 8. 자동배포 작동 확인

로컬에서:
```bash
echo "<!-- deploy test -->" >> static/index.html
git add static/index.html
git commit -m "deploy test"
git push origin main
```

5초 후:
```bash
curl -s http://163.192.35.70:8000/ | grep "deploy test"
```

검색되면 성공. **이제부터는 사용자/Claude 누구든 `git push` 만으로 운영 반영됨.**

---

## 다음에 SSH 다시 들어가야 하는 경우

- DEPLOY_SECRET 을 새로 바꿀 때 (`.env` + GitHub Webhook 둘 다 수정)
- 의존성 추가 — requirements.txt 변경 시 `pip install -r requirements.txt` 한 번
- Python 버전 업그레이드 등 OS 레벨 작업
- 그 외에는 **들어갈 일 없음**

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| GitHub Webhook 에서 `timeout` | OCI Security List 미개방 | §A 다시 확인 |
| GitHub Webhook 에서 `connection refused` | 서버가 8000 에 안 떠있음 | `curl localhost:8000/api/health` 로 확인. 안 뜨면 `tail -50 run.log` |
| GitHub Webhook 에서 `403 invalid signature` | 시크릿 불일치 | `echo $DEPLOY_SECRET` vs GitHub Webhook Secret 비교 |
| `git pull` 실패 | 권한 문제 또는 충돌 | `cd ~/allersafe && git status && git pull origin main` 수동 실행해서 에러 메시지 확인 |
| 외부에서 접속 안됨 | iptables 닫혀있음 | §3 다시 실행 |
| 재부팅 후 안 뜸 | systemd 미등록 | §6 진행 |
