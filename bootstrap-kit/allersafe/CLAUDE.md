# allersafe — Claude Code 작업 가이드

> 이 레포는 **chart 와 같은 자동배포 패턴**을 그대로 가져왔습니다.
> 시스템 구조 상세는 chart 레포의 `docs/APP_INTERACTION_FLOW.md` 참고.

## 핵심 사실 (먼저 알아두기)

- **포트**: 5001 (chart 가 5000 을 쓰므로 충돌 회피)
- **호스트**: Oracle VM `163.192.35.70` (chart 와 동일 VM)
- **자동배포 경로**: 로컬 Edit → `git push origin main` → GitHub webhook → `http://163.192.35.70:5001/deploy` → 서버에서 `git pull` + `fuser -k` → `run.sh` 가 재기동
- **Oracle SSH 불필요**: 위 webhook 만 동작하면 push 만으로 운영 반영됨
- **DEPLOY_SECRET**: 환경변수 `DEPLOY_SECRET` 으로 주입 (Oracle `~/.bashrc` 또는 `.env` 에서 export)

## 파일 구조

```
allersafe/
├── server.py              ← Flask. /api/health, /deploy, 정적 서빙
├── setup.sh               ← 최초 설치 (pip + 디렉토리)
├── dev.sh                 ← 로컬 개발 루프 (자동 재기동)
├── run.sh                 ← 프로덕션 루프 (Oracle 에서 nohup)
├── claude-apply.sh        ← Claude 수정 후 즉시 반영 (구문검사+pkill+헬스체크)
├── requirements.txt       ← Python 의존성
├── static/index.html      ← 프런트엔드 (현재는 헬스체크용 스켈레톤)
├── output/                ← 데이터 캐시 (gitignore)
└── CLAUDE.md              ← 이 파일
```

## Claude 자동 반영 루프

```
1. 파일 Read → 위치 파악
2. Edit 으로 최소 diff 적용
3. bash claude-apply.sh 실행
   ├─ Python 구문 검사
   ├─ fuser -k 5001/tcp (기존 종료)
   ├─ python3 server.py & (백그라운드 기동)
   └─ /api/health 헬스체크 (10회, 1초 간격)
4. 사용자 명시적 요청 시에만 git add/commit/push
```

HTML 수정은 서버 재시작 불필요 — 브라우저 `Ctrl+Shift+R`.

## 변경 절차

### 로컬에서
```bash
# 파일 수정 후
bash claude-apply.sh
```

### 운영(Oracle) 반영
```bash
git add <files>
git commit -m "<요약>"
git push -u origin main
# → webhook 이 자동으로 git pull + 재기동
```

## 자주 쓰는 명령

```bash
# 헬스체크
curl http://localhost:5001/api/health

# 운영 서버
curl http://163.192.35.70:5001/api/health

# 서버 로그
tail -50 server.log

# 강제 재기동 (로컬)
fuser -k 5001/tcp; nohup python3 server.py &
```

## Oracle 운영 환경 위치

| 항목 | 경로/값 |
|---|---|
| 서버 IP | `163.192.35.70` |
| 포트 | `5001` |
| 설치 경로 | `/home/<user>/allersafe` (Oracle VM 안) |
| 프로세스 관리 | `run.sh` 가 `while true` 루프로 감시 |
| 자동배포 | GitHub webhook → `POST /deploy` (HMAC) |

## 주의

- **DEPLOY_SECRET 을 코드에 박지 말 것**: 환경변수만 사용
- **포트 5001 이 OCI Security List 에서 열려 있어야** webhook 도착함
- **`POPULAR_STOCKS` 같은 외부 데이터**는 별도 추가. 이 스켈레톤엔 없음
- chart 와 같은 Oracle VM 이므로 **포트만 다르고 동일 호스트** — DNS/도메인 분리하려면 nginx 별도 설정 필요
