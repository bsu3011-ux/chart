# 멀티마켓 트레이딩 봇 — Claude Code 작업 가이드

## 프로젝트 개요

Flask 기반 주식/지수 시그널 분석 웹앱. 단일 HTML 파일(React 18 + Babel CDN)과 Python 백엔드로 구성.

- **서버 주소**: `http://localhost:5000`
- **프로젝트 경로**: `/home/user/chart`
- **git 브랜치**: `main`

---

## 파일 구조

```
/home/user/chart/
├── static/
│   └── index.html          ← 프론트엔드 전체 (React JSX, Babel CDN)
├── server.py               ← Flask API 서버
├── multi_market_bot_v4.py  ← 시그널 분석 로직, MARKETS, POPULAR_STOCKS
├── crypto_data.py          ← 크립토 데이터 유틸
├── run.sh                  ← 서버 자동재시작 루프
├── output/
│   └── signals_v4.json     ← 분석 결과 캐시
└── CLAUDE.md               ← 이 파일
```

---

## 변경사항 적용 방법

### 1단계: 파일 수정
```bash
# 프론트엔드 수정
Edit /home/user/chart/static/index.html

# 백엔드(API) 수정
Edit /home/user/chart/server.py

# 봇 로직/종목 수정
Edit /home/user/chart/multi_market_bot_v4.py
```

### 2단계: 커밋 & 푸시
```bash
git add static/index.html server.py multi_market_bot_v4.py
git commit -m "변경 내용 요약"
git push -u origin main
```

### 3단계: 서버 재시작
```bash
fuser -k 5000/tcp 2>/dev/null; sleep 1; python3 server.py &
```

### 4단계: 확인
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/
# → 200 이면 정상
```

---

## 자주 쓰는 명령어

```bash
# 서버 로그 확인
tail -50 /home/user/chart/server.log

# 서버 프로세스 확인
fuser 5000/tcp

# 서버 강제 재시작
fuser -k 5000/tcp 2>/dev/null; sleep 1; python3 server.py &

# git 상태 확인
git log --oneline -5
git diff HEAD

# 패키지 설치 (필요시)
pip install flask flask-cors yfinance pandas numpy --break-system-packages
```

---

## 주요 API 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /` | 메인 페이지 (index.html) |
| `GET /api/signals` | 현재 시그널 JSON |
| `GET /api/run` | 수동 분석 실행 |
| `GET /api/status` | 서버 상태 |
| `GET /api/forex` | 환율 데이터 |
| `GET /api/sectors` | 섹터 히트맵 데이터 |
| `GET /api/search?q=삼성` | 종목 검색 |
| `GET /api/chart?ticker=^KS11` | 차트 데이터 |
| `GET /countries-110m.json` | 세계지도 TopoJSON |
| `POST /deploy` | GitHub webhook (자동 배포) |

---

## 프론트엔드 구조 (index.html)

단일 파일에 모든 React 컴포넌트가 포함됨. CDN 스크립트:
- React 18, ReactDOM 18
- Babel Standalone (JSX 변환)
- Lightweight Charts (캔들차트)
- D3 v7 + TopoJSON Client v3 (세계지도)

### 주요 컴포넌트
```
App
├── GlobalStyles          ← CSS (미디어쿼리, 애니메이션)
├── SideNav               ← 데스크탑 좌측 네비게이션
├── MarketTab             ← 메인 탭 (지도 + 지수 카드)
│   ├── FearGreedWidget   ← 공포탐욕 지수
│   ├── ForexBoard        ← 환율 보드
│   ├── WorldMap          ← D3 세계지도 + 마켓 버블
│   └── SectorHeatmap     ← 섹터 트리맵/카드
├── ScreenerPage          ← 스크리너
├── PortfolioPage         ← 포트폴리오
├── CalendarPage          ← 경제 캘린더
└── BottomTabBar          ← 모바일 하단 탭바
```

### 색상 토큰
`C.green`, `C.red`, `C.cyan`, `C.text`, `C.dim`, `C.muted`, `C.border`, `C.card`, `C.surface` 등 → 파일 상단 `const C = {...}` 참조

### 반응형 CSS 클래스
| 클래스 | 설명 |
|--------|------|
| `.app-wrap` | 메인 컨테이너 (모바일 480px / 데스크탑 1200px) |
| `.bottom-nav` | 하단 탭바 (데스크탑에서 숨김) |
| `.side-nav` | 좌측 네비 (모바일에서 숨김) |
| `.desktop-grid` | 2열 그리드 (데스크탑만) |
| `.desktop-full` | 전체 너비 (grid 안에서) |

---

## 봇 데이터 수정

### 종목 추가 (검색에 표시) — `multi_market_bot_v4.py`
```python
POPULAR_STOCKS = {
    "005930.KS": {"name": "삼성전자", "name_en": "Samsung Electronics",
                  "sector": "반도체", "flag": "🇰🇷"},
    # 추가할 종목 여기에...
}
```

### 지수 추가 (시그널 분석 대상) — `multi_market_bot_v4.py`
```python
MARKETS = {
    "^GSPC": {
        "name": "S&P 500", "symbol": "SPX", "flag": "🇺🇸",
        "strategy": "leverage",   # leverage / risk_defense / dual_filter / minervini
        "params": {"check_interval": 5},
        "period": "2y",
    },
    # 추가할 지수 여기에...
}
```

### 세계지도에 지수 표시 — `index.html`
```javascript
const GEO_COORDS = {
    "^GSPC": {lon: -97, lat: 39, label: "S&P500"},
    // lon/lon: 실제 위도/경도, label: 지도에 표시될 이름
};
```

---

## 배포 흐름

```
Claude Code에서 수정
       ↓
git push origin main
       ↓
GitHub → /deploy webhook (POST)
       ↓
서버에서 git pull origin main
       ↓
서버 자동 재시작 (run.sh 루프)
       ↓
브라우저에서 새로고침 → 변경사항 반영
```

> **주의**: `/deploy` webhook에는 시크릿 키가 필요  
> `DEPLOY_SECRET = "stockbot-deploy-2024"` (server.py)

---

## 자주 발생하는 문제

| 증상 | 원인 | 해결 |
|------|------|------|
| 화면이 안 켜짐 | JS 문법 오류 | `curl localhost:5000` 으로 HTML 확인, 브라우저 콘솔 확인 |
| 포트 이미 사용 중 | 이전 서버 좀비 프로세스 | `fuser -k 5000/tcp` |
| 변경사항 미반영 | 브라우저 캐시 | Ctrl+Shift+R (강력 새로고침) 또는 시크릿 창 |
| git push 실패 | 네트워크 | 최대 4회 재시도: 2s → 4s → 8s → 16s |
| yfinance 오류 | 패키지 없음 | `pip install yfinance --break-system-packages` |
| 지도가 안 나옴 | D3 CDN 로드 실패 | 재시도 루프 내장 (200ms마다), 잠시 후 자동 복구 |
