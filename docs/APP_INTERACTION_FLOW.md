# 앱 조작 요청 처리 흐름 — Claude 작업 가이드

> 이 문서는 사용자가 "이 앱을 이렇게 바꿔줘" 라고 요청했을 때
> Claude 가 **어디를 보고 / 어떻게 분석하고 / 어떤 순서로 수정·배포** 하는지를
> 다른 Claude 세션이 곧바로 따라할 수 있도록 정리한 작업 매뉴얼이다.
>
> 짝꿍 문서: 프로젝트 루트의 `CLAUDE.md` (개요/명령어 모음)
> 본 문서는 **요청을 분류하고 실제 변경을 만드는 사고 흐름**에 초점을 둔다.

---

## 0. 큰 그림 (한눈 요약)

```
사용자 요청 (자연어)
        │
        ▼
[1] 요청 분류
   ├─ UI/표시 변경      → static/index.html
   ├─ API/데이터 변경   → server.py
   ├─ 시그널/종목 변경  → multi_market_bot_v4.py
   └─ 인프라/배포 변경  → run.sh / restart.sh / CLAUDE.md
        │
        ▼
[2] 대상 파일 Read → 영향 범위 식별
        │
        ▼
[3] Edit 적용 (최소 diff)
        │
        ▼
[4] 검증
   ├─ python3 -c "import server" 등 구문 체크
   ├─ curl http://localhost:5000/api/... 으로 응답 확인
   └─ 브라우저 캐시 무력화는 server.py 가 이미 처리(Cache-Control: no-cache)
        │
        ▼
[5] 커밋 & 푸시 (main)
        │
        ▼
[6] /deploy webhook → 서버 git pull → pkill → run.sh 가 재기동
```

---

## 1. 시스템 구성 요소와 역할

| 계층 | 파일 | 역할 | 변경 빈도 |
|---|---|---|---|
| 프런트엔드 | `static/index.html` (≈2,000줄) | React 18 + Babel CDN 단일 파일. 모든 UI 컴포넌트 + fetch 호출 | **매우 잦음** |
| API | `server.py` (≈550줄) | Flask. 정적 서빙 + 11개 API 엔드포인트 + GitHub webhook (`/deploy`) | 자주 |
| 분석 엔진 | `multi_market_bot_v4.py` (≈1,300줄) | `MARKETS`, `POPULAR_STOCKS`, `analyze_stock`, 전략별 분석기, `main()` 배치 | 종목·전략 추가 시 |
| 크립토 보조 | `crypto_data.py` | 크립토 유틸 (필요 시 import) | 드묾 |
| 시그널 캐시 | `output/signals_v4.json` | `main()` 결과를 저장 → `/api/signals` 가 그대로 서빙 | 자동 갱신 |
| 자동 재기동 | `run.sh` | `while true; do python3 server.py; sleep 3; done` — 죽으면 3초 후 재기동 | 거의 없음 |
| 수동 재기동 | `restart.sh` | (배포 환경 전용 경로 `/home/ubuntu/stock-bot`) | 거의 없음 |
| 정적 자산 | `static/countries-110m.json` | D3 세계지도 TopoJSON | 변경 없음 |
| 지침 | `CLAUDE.md` | 작업 가이드 (현재 문서의 상위본) | 가끔 |

### 핵심 흐름 한 줄 요약
- **읽기 경로**: 브라우저 → `GET /api/signals` → `output/signals_v4.json` 디스크 파일 그대로 응답
- **갱신 경로**: 브라우저 "수동 갱신" 버튼 → `GET /api/run` → `multi_market_bot_v4.main()` 동기 실행 → JSON 저장 → 응답
- **개별 종목**: 검색창 → `GET /api/stock_analysis?ticker=...` → `analyze_stock(ticker)` 실시간 호출 (캐시 없음)
- **배포**: `git push origin main` → GitHub → `POST /deploy` (HMAC 검증) → 서버에서 `git pull` 후 `pkill` → `run.sh` 가 재기동

---

## 2. 요청 분류 — "어디를 만져야 하는가"

사용자 자연어 요청을 받으면 먼저 다음 표로 분류한다.

| 요청 키워드/예시 | 1차 수정 파일 | 보통 같이 봐야 하는 파일 |
|---|---|---|
| "버튼 색을, 폰트을, 카드 모양을…" | `static/index.html` (`const C = {...}` 색상 토큰, 또는 컴포넌트 인라인 스타일) | — |
| "탭 추가/이름 변경" | `static/index.html` (`App()` 의 `tab` state, `SideNav`/`BottomTabBar`) | — |
| "지도/세계지도 변경" | `static/index.html` (`WorldMap`, `GEO_COORDS`) | — |
| "환율/공포탐욕/섹터 표시 바꿔" | `static/index.html` 의 `ForexBoard`/`FearGreedWidget`/`SectorHeatmap` | `server.py` 의 `/api/forex`, `/api/fear_greed`, `/api/sectors` |
| "차트에 지표 추가 (RSI, MACD, MA…)" | `static/index.html` (`ChartModal`, `calcRSIdata`/`calcMACDdata`/`calcMAforChart`) | — |
| "검색에 종목 추가" | `multi_market_bot_v4.py` 의 `POPULAR_STOCKS` | — |
| "지수 추가 (시그널 분석 대상)" | `multi_market_bot_v4.py` 의 `MARKETS` + `static/index.html` 의 `GEO_COORDS`, 그리고 `main()` 의 `categories` 분류 | — |
| "전략 로직 (RSI 임계값, MA 기간, ATR 등)" | `multi_market_bot_v4.py` (`analyze_minervini`/`leverage`/`dual_filter`/`risk_defense`) | — |
| "개별 종목 분석 문구/위험도/전망" | `multi_market_bot_v4.py` 의 `_generate_signal`, `_generate_analysis_text`, `_generate_forecasts`, `_assess_risk` | — |
| "환율 통화쌍 추가" | `server.py` 의 `/api/forex` `pairs` 리스트 | — |
| "캘린더 이벤트 추가" | `server.py` 의 `/api/calendar` `events` 리스트 (정적) | — |
| "섹터 ETF/구성종목" | `server.py` 의 `/api/sectors` `us_sector_map` / `kr_sector_map` | — |
| "API 추가" | `server.py` 에 `@app.route` 추가 | `static/index.html` 에서 `fetch(${API_BASE}/...)` 호출 |
| "포트 변경 / 환경변수 / 로그" | `server.py` 의 `__main__`, `run.sh` | `CLAUDE.md` 업데이트 |
| "자동 배포가 안 돌아" | `server.py` `/deploy` 핸들러, `DEPLOY_SECRET`, `run.sh` | — |

---

## 3. 프런트엔드 구조 (index.html)

CDN 의존성: React 18, Babel Standalone, lightweight-charts 4.1.3, D3 v7, topojson-client v3.

### 상수
- `API_BASE` — `localhost` 면 `http://localhost:5000`, 그 외엔 `window.location.origin`
- `C` — 색상 토큰 (`green`, `red`, `cyan`, `text`, `dim`, `card`, `border` …)
- `SIG` — 시그널 타입 → 색 매핑 (`LEVERAGE_2X`, `HOLD_1X`, `CASH`, `INVESTED`, `BUY`, `STRONG_BUY`, `CAUTION`, `NEUTRAL` …)
- `fp(value, ticker)` — 티커 접미사에 따른 통화/포맷 (`.KS` → 원, `.T` → 엔, `^FCHI` → 유로 …)

### 지표 계산 (브라우저 측)
`calcEMA`, `calcMAforChart`, `calcRSIdata`, `calcMACDdata` — `ChartModal` 의 보조 패널 그리는 데 사용. 백엔드 값과 별개로 다시 계산함.

### 주요 컴포넌트 트리
```
App (state: data, tab, loading, apiConnected, clock, chartMarket)
├── GlobalStyles                 ← 미디어쿼리·애니메이션 CSS 주입
├── 배경 글로우 divs
├── (tab==="market")    MarketTab
│   ├── TopSearchBar             ← 종목 자동완성 (검색 → /api/search_stocks → /api/stock_analysis)
│   ├── FearGreedWidget          ← /api/fear_greed
│   ├── ForexBoard               ← /api/forex
│   ├── WorldMap                 ← D3 + /countries-110m.json + GEO_COORDS
│   ├── SectorHeatmap            ← /api/sectors
│   └── Card[] (지수 카드)        ← data.markets 로 렌더, 클릭하면 ChartModal
├── (tab==="screener")  ScreenerPage
├── (tab==="portfolio") PortfolioPage   ← localStorage 보유종목, /api/chart 로 현재가
├── (tab==="calendar")  CalendarPage    ← /api/calendar
├── (tab==="settings")  SettingsPage
├── SideNav                      ← 데스크탑 좌측
├── BottomTabBar                 ← 모바일 하단
└── ChartModal (chartMarket≠null) ← /api/chart?ticker=&interval=
```

### 자동 갱신 주기
- `App.fetchSignals` 가 5분(`5*60*1000`)마다 `/api/signals` 폴링
- "시계" 는 1초마다 setState (`clock`) — 헤더 시각 표시
- 다른 위젯은 자체 `useEffect` 안에서 첫 로드 1회만 fetch

### 데모 데이터
`data` 의 초깃값은 `DEMO_DATA` (파일 안에 정의). API 가 실패하면 데모로 화면이 보임 — 즉 **백엔드가 죽어도 프런트는 죽지 않는다**. 디버깅 시 `apiConnected` 가 false 면 API 단계를 의심.

### 반응형 CSS
- `.app-wrap` 모바일 480px / 데스크탑 1200px
- `.bottom-nav` 데스크탑 숨김, `.side-nav` 모바일 숨김
- `.desktop-grid` / `.desktop-full` — 데스크탑 2열 그리드 안에서 전체 너비 강제

---

## 4. 백엔드 (server.py) 엔드포인트 매트릭스

| 라우트 | 메서드 | 입력 | 데이터 출처 | 캐시? |
|---|---|---|---|---|
| `/` | GET | — | `static/index.html` | `no-cache` 강제 |
| `/guide` | GET | — | `static/guide.html` | — |
| `/countries-110m.json` | GET | — | 정적 파일 | — |
| `/api/signals` | GET | — | `output/signals_v4.json` 디스크 | 디스크에 의존 |
| `/api/run` | GET | — | `multi_market_bot_v4.main()` 동기 실행 → JSON 저장 | 즉시 갱신 |
| `/api/status` | GET | — | 파일 mtime | — |
| `/api/stock_analysis` | GET | `ticker` (대문자 강제, 6자리 숫자면 `.KS` 자동보완) | `analyze_stock()` 실시간 | 없음. yfinance 실패시 `POPULAR_STOCKS` 메타로 폴백 |
| `/api/search_stocks` | GET | `q` | `POPULAR_STOCKS` in-memory | 즉시 |
| `/api/chart` | GET | `ticker`, `interval` (1d/1wk/1mo) | yfinance 실시간 | 없음 |
| `/api/fear_greed` | GET | — | alternative.me + `^VIX` yfinance | 없음 |
| `/api/forex` | GET | — | yfinance | 없음 |
| `/api/calendar` | GET | — | 코드 안 하드코딩 events | 정적 |
| `/api/sectors` | GET | — | yfinance bulk download (US ETF + 한국 개별) | 없음 |
| `/deploy` | POST | GitHub webhook body | HMAC-SHA256 검증 → `git pull` → `pkill` | — |

### 직렬화 안전망
`_clean()` 헬퍼가 `NaN`/`Infinity` → `None` 으로 변환해 JSON 직렬화 오류 방지. 새 엔드포인트에 yfinance 값이 들어가면 같은 함수로 감싸라.

### 알아둘 함정
- `/api/run` 은 **동기 + 블로킹**. 전체 `MARKETS` 분석이 끝날 때까지 응답을 막는다 (수십 초). 프런트 `runAnalysis` 가 `setLoading(true)` 로 가리지만, 운영 환경에서 한 클라이언트가 누르면 동안 다른 요청들이 정체될 수 있다.
- `/api/run` 은 `asyncio.new_event_loop()` 로 자체 루프를 만든다. **이미 이벤트 루프 안에서 호출되면 충돌**한다 — Flask 동기 핸들러라 정상 동작 중이지만, 이를 `async` 핸들러나 ASGI 로 옮기려면 손봐야 한다.
- `/deploy` 는 `DEPLOY_SECRET = "stockbot-deploy-2024"` 로 HMAC 검증. 비밀키 자체는 코드에 박혀 있다 — 운영 보안 강화가 필요하면 환경변수로 빼라.

---

## 5. 분석 엔진 (multi_market_bot_v4.py)

### 두 가지 데이터 모델
1. **`MARKETS`** — 지수/ETF/크립토 등 "시그널 카드" 에 표시될 대상. 각 항목에 `strategy` 필드:
   - `minervini` — 추세추종 (MA/ATR 트레일)
   - `leverage` — 2x / 1x / 0x 스위칭
   - `dual_filter` — 이중필터 모멘텀
   - `risk_defense` — 위기방어형
2. **`POPULAR_STOCKS`** — 개별 종목 검색용 메타데이터 (`name`, `name_en`, `sector`, `flag`). 시그널 분석 대상 아님.

### 호출 그래프
```
server.py
├── /api/run   → main()  ─┐
│                          ├─ for ticker in MARKETS:
│                          │     load_data(ticker)
│                          │     analyze_market(ticker, info, df)
│                          │       ├ analyze_minervini   / leverage
│                          │       ├ analyze_dual_filter / risk_defense
│                          │     ↓
│                          └─ save_json(all_results) → output/signals_v4.json
│
└── /api/stock_analysis → analyze_stock(ticker)
                          ├ load_data
                          ├ calc_rsi / calc_atr / calc_macd / calc_bollinger / calc_volume_analysis
                          ├ _generate_signal
                          ├ _generate_analysis_text
                          ├ _generate_forecasts
                          ├ _assess_risk
                          └ _build_price_history  (스파크라인용 20포인트)
```

### 시그널 표시 흐름
`analyze_market` 의 결과는 `r['signal_type']` 으로 분류되고, `static/index.html` 의 `SIG` 사전이 색을 매핑한다. **새 시그널 타입을 만들면 `SIG` 에도 반드시 추가**해야 카드가 회색이 안 된다.

### 카테고리 (배치 출력 순서)
`main()` 안의 `categories` dict 가 텔레그램·콘솔 출력 순서를 결정. 새 티커를 `MARKETS` 에 넣어도 어느 카테고리에 안 잡히면 출력에서 누락된다 → `categories` 의 조건식도 확인.

---

## 6. 변경 → 배포 표준 절차

### Step 1 — 분류 후 Read
```
Read static/index.html  ← UI 면
Read server.py          ← API 면
Read multi_market_bot_v4.py  ← 시그널·종목 면
```
파일이 크므로 `grep -n` 으로 위치 먼저 잡고, `Read(offset=, limit=)` 으로 좁혀 읽는다.

### Step 2 — Edit
- **최소 diff** 원칙. 주변 정리/리팩토링 자제.
- 색상은 토큰(`C.green` 등) 직접 참조. 인라인 hex 새로 도입하지 말 것.
- 새 API 라우트는 `_clean()` 으로 감싸 JSON 안전 보장.
- 새 시그널 타입은 `static/index.html` 의 `SIG` 객체에 키 추가 필수.

### Step 3 — 서버 재시작
```bash
fuser -k 5000/tcp 2>/dev/null; sleep 1; python3 server.py &
```
- `run.sh` 가 외부 루프로 돌고 있는 환경이면 `pkill -f "python3 server.py"` 만 해도 자동 재기동.
- 5000 포트가 이미 점유돼 있으면 `fuser -k` 우선.

### Step 4 — 검증
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/
curl -s http://localhost:5000/api/status
curl -s "http://localhost:5000/api/stock_analysis?ticker=AAPL" | head -c 400
```
프런트 변경이면 시크릿창/`Ctrl+Shift+R` 로 강력 새로고침. `server.py` 가 이미 `Cache-Control: no-cache` 를 헤더로 박아주므로 보통은 그냥 새로고침으로 충분.

### Step 5 — 커밋 & 푸시
사용자가 명시적으로 요청했을 때만.
```bash
git add static/index.html server.py multi_market_bot_v4.py
git commit -m "<요약>"
git push -u origin main         # ※ 발판 브랜치면 그 브랜치로
```
네트워크 실패 시 2s → 4s → 8s → 16s 지수 백오프로 최대 4회 재시도.

### Step 6 — 자동 배포
GitHub 가 `POST /deploy` 로 webhook 호출 → 서버가 `git pull origin main` → 별도 쓰레드에서 `pkill -f "python3 server.py"` → `run.sh` 루프가 새 코드로 재기동. **수동 개입 불필요**.

---

## 7. 디버깅 결정 트리

```
증상: "화면이 안 보여요 / 데이터가 안 떠요"
  │
  ├─ curl http://localhost:5000/ → 200 아님?
  │     └─ 서버가 죽음. server.log 확인 → 보통 multi_market_bot_v4.py 임포트 에러
  │
  ├─ 200 인데 화면이 회색/데모 데이터?
  │     └─ apiConnected=false. /api/signals 가 404 (signals_v4.json 없음)
  │         → curl http://localhost:5000/api/run 으로 1회 분석 강제
  │
  ├─ 종목 검색이 비어 있음?
  │     └─ POPULAR_STOCKS 에 없음. 종목 추가 필요
  │
  ├─ 시그널 카드가 회색?
  │     └─ signal_type 이 SIG 사전에 없음. index.html SIG 보강
  │
  ├─ 지도에 지수 안 보임?
  │     └─ GEO_COORDS 에 ticker 없음
  │
  ├─ 차트가 안 그려짐?
  │     └─ /api/chart?ticker=... 응답 확인. yfinance 가 빈 DF 리턴이면 ticker 표기 점검
  │
  └─ "변경했는데 반영 안 됨"
        ├─ 서버 재시작 안 했음 → fuser -k 5000/tcp
        └─ 브라우저 캐시 → Ctrl+Shift+R / 시크릿창
```

---

## 8. 사용자 요청 → 변경 매핑 예시

### 예 1) "BTC 카드 색을 더 진한 주황으로"
- `static/index.html` 의 `C.orange` 또는 `SIG[BTC 의 signal_type]` 의 `c` 값 후보. 다만 `C` 는 전역 토큰이라 다른 컴포넌트에도 영향. 가능하면 BTC 카드만 분기.
- 영향 범위: `Card({m,...})` 컴포넌트가 `SIG[m.signal_type]` 으로 배경을 칠함 — `m.ticker === 'BTC-USD'` 분기 한 줄로 처리.

### 예 2) "한국 방산 ETF 섹터 카드 추가"
- 데이터: `server.py` `/api/sectors` 의 `kr_sector_map` 에 항목 추가 (이미 "방위산업" 있음 → 구성종목 보강).
- UI: 자동 반영 (`SectorHeatmap` 이 `kr_sectors` 그대로 그림).

### 예 3) "삼성SDI 검색되게 해줘"
- `multi_market_bot_v4.py` `POPULAR_STOCKS` 에 `"006400.KS": {...}` 추가 (이미 있음 — 비슷한 사례 확인 후 메타 보강).

### 예 4) "RSI 14 대신 9 쓰자"
- 백엔드 분석값: `multi_market_bot_v4.py` `calc_rsi(c, p=14)` 기본값 변경 또는 호출부에 `p=9` 전달.
- 프런트 차트 보조 패널: `static/index.html` `calcRSIdata(candles, period=14)` 기본값.
- **둘 다 바꿔야** 사용자가 보는 값과 시그널이 일치한다.

### 예 5) "캘린더가 정적인데 실제 데이터를 받아오게"
- `server.py` `/api/calendar` 가 하드코딩 리스트라는 점을 사용자에게 먼저 알리고, 외부 소스 (Investing/forexfactory) 선택지를 제안. 데이터 폴링은 비용·신뢰성 의사결정이 필요한 영역 — 임의로 진행하지 말 것.

---

## 9. 안전 가드레일

- **루트(.gitignore 외 비밀 파일) 커밋 금지**: `DEPLOY_SECRET` 은 이미 노출돼 있으나, 새 토큰을 코드에 박지 말 것.
- **`/api/run` 을 자동화 루프에서 호출하지 말 것**: 동기 + 무거움. 자동 갱신은 외부 cron 또는 별도 워커로.
- **`MARKETS` 추가 시 `period`/`strategy`/`params` 누락 금지**: `analyze_market` 가 KeyError.
- **`POPULAR_STOCKS` 키 형식**: 미국=대문자 티커, 한국=`NNNNNN.KS`/`.KQ`. 6자리 숫자는 server 가 `.KS` 자동보완하지만, 코스닥(`.KQ`) 은 명시 필요.
- **JSON 직렬화**: yfinance 결과는 `NaN` 이 자주 섞임 → `_clean()` 으로 감쌀 것.
- **HMR 없음**: 단일 HTML + 서버 사이드 정적 서빙. 변경 시 항상 서버 재기동 + 브라우저 새로고침.

---

## 10. 새 Claude 세션이 처음 들어왔을 때 추천 순서

1. `CLAUDE.md` 1분 스캔 (개요/명령어)
2. 본 문서 §1, §2 로 분류 감각 잡기
3. 실제 작업 들어가기 전:
   ```bash
   git status && git log --oneline -5
   curl -s http://localhost:5000/api/status
   ```
4. 변경 대상 파일을 `grep -n` 으로 위치 잡고 → `Read` 좁혀서 읽고 → `Edit`
5. 검증 끝나면 사용자 승인 후에만 `git commit && git push`

