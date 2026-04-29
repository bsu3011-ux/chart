#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  멀티마켓 봇 v4.0 — API 서버
  ───────────────────────────────────────────
  1) 봇이 주기적으로 분석 → signals_v4.json 저장
  2) Flask API가 JSON을 서빙 → 앱에서 fetch
  3) 수동 실행 엔드포인트도 제공
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, json, asyncio, datetime, threading, urllib.request, hmac, hashlib, subprocess
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

# ── 봇 임포트 ──
from multi_market_bot_v4 import (
    main as run_bot, MARKETS, load_data, analyze_market, save_json,
    analyze_stock, POPULAR_STOCKS,
)

# ── 절대 경로 기준 설정 ──
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)
CORS(app)  # 모든 도메인 허용

OUTPUT_DIR   = os.environ.get("OUTPUT_DIR", os.path.join(BASE_DIR, "output"))
SIGNALS_FILE = os.path.join(OUTPUT_DIR, "signals_v4.json")
os.makedirs(OUTPUT_DIR,   exist_ok=True)
os.makedirs(STATIC_DIR,   exist_ok=True)


@app.route('/api/signals')
def get_signals():
    """현재 시그널 JSON 반환"""
    if os.path.exists(SIGNALS_FILE):
        with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    else:
        return jsonify({"error": "아직 분석 결과가 없습니다. /api/run 으로 실행하세요."}), 404


@app.route('/api/run')
def run_analysis():
    """수동으로 봇 실행"""
    try:
        # 비동기 함수를 동기로 실행
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())
        loop.close()
        
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({"status": "success", "data": data})
        else:
            return jsonify({"status": "error", "message": "분석 완료했지만 파일 생성 실패"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/status')
def status():
    """서버 상태 확인"""
    last_updated = None
    if os.path.exists(SIGNALS_FILE):
        mtime = os.path.getmtime(SIGNALS_FILE)
        last_updated = datetime.datetime.fromtimestamp(mtime).isoformat()
    
    return jsonify({
        "status": "running",
        "version": "4.0",
        "markets": len(MARKETS),
        "last_updated": last_updated,
        "signals_file": SIGNALS_FILE,
    })


@app.route('/api/stock_analysis')
def get_stock_analysis():
    """개별 주식 기술적 분석
    GET /api/stock_analysis?ticker=AAPL
    GET /api/stock_analysis?ticker=005930.KS
    """
    ticker = request.args.get('ticker', '').strip().upper()
    if not ticker:
        return jsonify({"error": "ticker 파라미터가 필요합니다 (예: ?ticker=AAPL)"}), 400

    # 6자리 숫자 → .KS 자동 보완 (예: 005930 → 005930.KS)
    if ticker.isdigit() and len(ticker) == 6:
        ticker = ticker + ".KS"

    try:
        result = analyze_stock(ticker)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"분석 실패: {str(e)}"}), 500


@app.route('/api/search_stocks')
def search_stocks():
    """인기 주식 검색 (이름/티커 매칭)
    GET /api/search_stocks?q=삼성
    GET /api/search_stocks?q=Apple
    """
    q = request.args.get('q', '').strip().lower()
    results = []
    for ticker, info in POPULAR_STOCKS.items():
        if not q:
            results.append({"ticker": ticker, **info})
        else:
            if (q in ticker.lower()
                    or q in info.get("name", "").lower()
                    or q in info.get("name_en", "").lower()
                    or q in info.get("sector", "").lower()):
                results.append({"ticker": ticker, **info})
        if len(results) >= 15:
            break
    return jsonify({"results": results})


@app.route('/api/chart')
def get_chart_data():
    """캔들스틱 차트 데이터 (일봉/주봉/월봉)
    GET /api/chart?ticker=^KS11&interval=1d
    interval: 1d (일봉/1년), 1wk (주봉/3년), 1mo (월봉/5년)
    """
    import yfinance as yf
    import pandas as pd

    ticker   = request.args.get('ticker', '').strip()
    interval = request.args.get('interval', '1d')
    if not ticker:
        return jsonify({"error": "ticker 파라미터 필요"}), 400

    period_map = {'1d': '1y', '1wk': '3y', '1mo': '5y'}
    if interval not in period_map:
        interval = '1d'
    period = period_map[interval]

    try:
        df = yf.download(ticker, period=period, interval=interval,
                         auto_adjust=True, progress=False, threads=False)
        if df is None or df.empty:
            return jsonify({"error": f"데이터 없음: {ticker}"}), 404

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        candles = []
        for idx, row in df.iterrows():
            try:
                o = float(row['Open']);  h = float(row['High'])
                l = float(row['Low']);   c = float(row['Close'])
                if any(pd.isna(x) for x in [o, h, l, c]):
                    continue
                try:
                    v = int(row['Volume']) if not pd.isna(row['Volume']) else 0
                except:
                    v = 0
                candles.append({
                    "time":   idx.strftime('%Y-%m-%d'),
                    "open":   round(o, 4),
                    "high":   round(h, 4),
                    "low":    round(l, 4),
                    "close":  round(c, 4),
                    "volume": v,
                })
            except Exception:
                continue

        return jsonify({"ticker": ticker, "interval": interval, "candles": candles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/fear_greed')
def get_fear_greed():
    """공포탐욕지수: 크립토(Alternative.me) + 주식(VIX 기반)"""
    import yfinance as yf
    import pandas as pd
    result = {}

    # ── 크립토 F&G (Alternative.me) ──
    try:
        with urllib.request.urlopen("https://api.alternative.me/fng/?limit=7", timeout=5) as r:
            crypto_fg = json.loads(r.read())
        items = crypto_fg.get("data", [])
        if items:
            latest = items[0]
            result["crypto"] = {
                "value": int(latest["value"]),
                "label": latest["value_classification"],
                "history": [{"date": d["timestamp"], "value": int(d["value"])} for d in items],
            }
    except Exception as e:
        result["crypto"] = {"value": 50, "label": "Neutral", "error": str(e)}

    # ── 주식 F&G (VIX 역산) ──
    try:
        vix_df = yf.download("^VIX", period="5d", interval="1d",
                             auto_adjust=True, progress=False, threads=False)
        if not vix_df.empty:
            if isinstance(vix_df.columns, pd.MultiIndex):
                vix_df.columns = vix_df.columns.get_level_values(0)
            vix_val = float(vix_df['Close'].iloc[-1])
            prev_vix = float(vix_df['Close'].iloc[-2]) if len(vix_df) > 1 else vix_val
            # VIX → 공포탐욕 (역산): VIX 낮을수록 탐욕
            if vix_val < 12:   fg, label = min(95, int(95 - vix_val)), "극단적 탐욕"
            elif vix_val < 17: fg, label = int(75 - (vix_val-12)*4), "탐욕"
            elif vix_val < 22: fg, label = int(55 - (vix_val-17)*4), "중립"
            elif vix_val < 30: fg, label = int(35 - (vix_val-22)*2), "공포"
            else:              fg, label = max(0, int(20 - (vix_val-30))), "극단적 공포"
            result["stock"] = {
                "value": max(0, min(100, fg)),
                "label": label,
                "vix": round(vix_val, 2),
                "vix_change": round(vix_val - prev_vix, 2),
            }
    except Exception as e:
        result["stock"] = {"value": 50, "label": "중립", "vix": 0, "error": str(e)}

    return jsonify(result)


@app.route('/api/forex')
def get_forex():
    """주요 환율 데이터"""
    import yfinance as yf
    import pandas as pd

    pairs = [
        ("USDKRW=X",  "USD/KRW",  "🇰🇷", "원"),
        ("USDJPY=X",  "USD/JPY",  "🇯🇵", "엔"),
        ("EURUSD=X",  "EUR/USD",  "🇪🇺", "유로"),
        ("GBPUSD=X",  "GBP/USD",  "🇬🇧", "파운드"),
        ("USDCNY=X",  "USD/CNY",  "🇨🇳", "위안"),
        ("USDINR=X",  "USD/INR",  "🇮🇳", "루피"),
        ("USDAUD=X",  "USD/AUD",  "🇦🇺", "호주달러"),
        ("BTC-USD",   "BTC/USD",  "₿",   "비트코인"),
    ]
    results = []
    for ticker, name, flag, unit in pairs:
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             auto_adjust=True, progress=False, threads=False)
            if df is None or df.empty: continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            cur  = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2]) if len(df) > 1 else cur
            chg  = (cur - prev) / prev * 100
            # 소수점 자리수 조절
            dec = 0 if cur > 100 else (2 if cur > 1 else 4)
            results.append({
                "ticker": ticker, "name": name, "flag": flag, "unit": unit,
                "rate": round(cur, dec),
                "change_pct": round(chg, 3),
                "prev": round(prev, dec),
            })
        except Exception:
            pass
    return jsonify({"rates": results, "generated_at": datetime.datetime.now().isoformat()})


@app.route('/api/calendar')
def get_calendar():
    """경제지표 캘린더 (이번 달 주요 이벤트)"""
    now   = datetime.datetime.now()
    y, m  = now.year, now.month
    today = now.strftime("%Y-%m-%d")

    def dt(day): return f"{y}-{m:02d}-{day:02d}"

    events = [
        # ── 미국 ──
        {"date":dt(1),  "country":"🇺🇸","name":"ISM 제조업 PMI",      "importance":"high",   "forecast":"49.5","previous":"49.2"},
        {"date":dt(2),  "country":"🇺🇸","name":"JOLTs 구인건수",       "importance":"medium", "forecast":"7.5M","previous":"7.6M"},
        {"date":dt(3),  "country":"🇺🇸","name":"ADP 민간 고용",        "importance":"medium", "forecast":"+180K","previous":"+155K"},
        {"date":dt(3),  "country":"🇺🇸","name":"ISM 서비스 PMI",       "importance":"medium", "forecast":"52.0","previous":"51.4"},
        {"date":dt(4),  "country":"🇺🇸","name":"비농업 고용 (NFP)",    "importance":"high",   "forecast":"+175K","previous":"+228K"},
        {"date":dt(4),  "country":"🇺🇸","name":"실업률",               "importance":"high",   "forecast":"4.1%","previous":"4.1%"},
        {"date":dt(7),  "country":"🇺🇸","name":"FOMC 의사록",           "importance":"high",   "forecast":"-","previous":"-"},
        {"date":dt(10), "country":"🇺🇸","name":"CPI (소비자물가)",      "importance":"high",   "forecast":"+0.2%","previous":"+0.2%"},
        {"date":dt(11), "country":"🇺🇸","name":"PPI (생산자물가)",      "importance":"medium", "forecast":"+0.2%","previous":"+0.0%"},
        {"date":dt(13), "country":"🇰🇷","name":"한국 CPI",              "importance":"medium", "forecast":"+2.1%","previous":"+2.0%"},
        {"date":dt(14), "country":"🇺🇸","name":"소매판매",              "importance":"medium", "forecast":"+0.3%","previous":"-0.9%"},
        {"date":dt(14), "country":"🇨🇳","name":"중국 산업생산·소매판매","importance":"medium", "forecast":"+5.6%","previous":"+5.9%"},
        {"date":dt(15), "country":"🇺🇸","name":"미시간 소비심리",       "importance":"low",    "forecast":"53.0","previous":"52.2"},
        {"date":dt(16), "country":"🇪🇺","name":"ECB 통화정책 결정",     "importance":"high",   "forecast":"2.25%","previous":"2.5%"},
        {"date":dt(23), "country":"🇺🇸","name":"S&P 글로벌 PMI (예비)", "importance":"medium", "forecast":"51.0","previous":"50.8"},
        {"date":dt(24), "country":"🇯🇵","name":"일본은행 금리결정",     "importance":"high",   "forecast":"0.5%","previous":"0.5%"},
        {"date":dt(25), "country":"🇺🇸","name":"GDP 성장률 (예비)",     "importance":"high",   "forecast":"+2.1%","previous":"+2.3%"},
        {"date":dt(28), "country":"🇰🇷","name":"한국은행 기준금리",     "importance":"high",   "forecast":"2.75%","previous":"2.75%"},
        {"date":dt(30), "country":"🇺🇸","name":"PCE 물가지수",          "importance":"high",   "forecast":"+2.5%","previous":"+2.5%"},
        {"date":dt(30), "country":"🇺🇸","name":"시카고 PMI",            "importance":"low",    "forecast":"45.5","previous":"47.6"},
    ]

    # 오늘 이후만, 날짜순 정렬
    filtered = sorted([e for e in events if e["date"] >= today], key=lambda x: x["date"])
    return jsonify({"events": filtered[:20], "generated_at": now.isoformat()})


@app.route('/api/sectors')
def get_sectors():
    """미국 섹터 ETF + 한국 독립 섹터 히트맵"""
    import yfinance as yf
    import pandas as pd

    # 미국: (ETF ticker, 섹터명, 이모지, [(US ticker, 종목명), ...])
    us_sector_map = [
        ("XLK",  "기술",       "💻", [("AAPL","애플"),("MSFT","MS"),("NVDA","엔비디아")]),
        ("SOXX", "반도체",     "🔬", [("NVDA","엔비디아"),("AMD","AMD"),("AVGO","브로드컴")]),
        ("XLF",  "금융",       "🏦", [("JPM","JP모건"),("BAC","뱅크오브아메리카"),("GS","골드만삭스")]),
        ("XLV",  "헬스케어",   "🏥", [("UNH","유나이티드헬스"),("LLY","일라이릴리"),("JNJ","존슨앤존슨")]),
        ("XBI",  "바이오",     "🧬", [("MRNA","모더나"),("BIIB","바이오젠"),("REGN","리제네론")]),
        ("XLY",  "경기소비재", "🛍️", [("AMZN","아마존"),("TSLA","테슬라"),("HD","홈디포")]),
        ("XLP",  "필수소비재", "🛒", [("PG","P&G"),("KO","코카콜라"),("WMT","월마트")]),
        ("XLE",  "에너지",     "⛽", [("XOM","엑슨모빌"),("CVX","셰브론"),("COP","코노코")]),
        ("ICLN", "클린에너지", "🌱", [("ENPH","인페이즈"),("FSLR","퍼스트솔라"),("RUN","선런")]),
        ("XLI",  "산업재",     "🏭", [("CAT","캐터필러"),("HON","허니웰"),("UPS","UPS")]),
        ("ITA",  "방위산업",   "🛡️", [("LMT","록히드마틴"),("RTX","RTX"),("NOC","노스럽그러먼")]),
        ("XLB",  "소재",       "⚗️", [("LIN","린데"),("FCX","프리포트"),("NEM","뉴몬트")]),
        ("XLRE", "리츠",       "🏢", [("AMT","아메리칸타워"),("PLD","프롤로지스"),("EQIX","에퀴닉스")]),
        ("XLC",  "통신/미디어","📡", [("META","메타"),("GOOGL","구글"),("NFLX","넷플릭스")]),
        ("XLU",  "유틸리티",   "⚡", [("NEE","넥스트에라"),("DUK","듀크에너지"),("SO","서던컴퍼니")]),
    ]

    # 한국 전용 섹터: (섹터명, 이모지, [(KR ticker, 종목명), ...])
    kr_sector_map = [
        ("반도체",      "🔬", [("005930.KS","삼성전자"),("000660.KS","SK하이닉스"),("042700.KS","한미반도체"),("000990.KS","DB하이텍")]),
        ("이차전지",    "🔋", [("373220.KS","LG에너지솔루션"),("006400.KS","삼성SDI"),("247540.KS","에코프로비엠"),("096770.KS","SK이노베이션")]),
        ("바이오/헬스", "🧬", [("207940.KS","삼성바이오"),("068270.KS","셀트리온"),("128940.KS","한미약품"),("000100.KS","유한양행")]),
        ("금융",        "🏦", [("105560.KS","KB금융"),("055550.KS","신한지주"),("086790.KS","하나금융"),("032830.KS","삼성생명")]),
        ("자동차",      "🚗", [("005380.KS","현대차"),("000270.KS","기아"),("012330.KS","현대모비스")]),
        ("조선",        "⚓", [("009540.KS","HD한국조선해양"),("042660.KS","한화오션"),("010620.KS","HD현대미포"),("011200.KS","HMM")]),
        ("방위산업",    "🛡️", [("012450.KS","한화에어로스페이스"),("047810.KS","KAI"),("064350.KS","현대로템")]),
        ("인터넷/플랫폼","🌐",[("035420.KS","네이버"),("035720.KS","카카오"),("259960.KS","크래프톤")]),
        ("엔터/콘텐츠", "🎵", [("352820.KS","HYBE"),("041510.KS","SM"),("122870.KS","YG엔터"),("035900.KS","JYP")]),
        ("화학/소재",   "⚗️", [("051910.KS","LG화학"),("011170.KS","롯데케미칼"),("006400.KS","삼성SDI")]),
        ("클린에너지",  "🌱", [("009830.KS","한화솔루션"),("373220.KS","LG에너지솔루션"),("247540.KS","에코프로비엠")]),
        ("에너지",      "⛽", [("010950.KS","S-Oil"),("096770.KS","SK이노베이션"),("078930.KS","GS")]),
        ("통신",        "📡", [("017670.KS","SK텔레콤"),("030200.KS","KT"),("032640.KS","LG유플러스")]),
        ("유통/소비재", "🛍️", [("023530.KS","롯데쇼핑"),("139480.KS","이마트"),("069960.KS","현대백화점")]),
        ("건설/인프라", "🏗️", [("000720.KS","현대건설"),("047040.KS","대우건설"),("034020.KS","두산에너빌리티")]),
    ]

    # 모든 티커 수집
    us_etf_tickers  = [s[0] for s in us_sector_map]
    us_stock_tickers = list({t for s in us_sector_map for t, _ in s[3]})
    kr_tickers = list({t for s in kr_sector_map for t, _ in s[2]})
    all_tickers = us_etf_tickers + us_stock_tickers + kr_tickers

    price_data = {}
    try:
        # 1개월 데이터로 1D/1W/1M 수익률 모두 계산
        df = yf.download(all_tickers, period="2mo", interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        close_df = df['Close'] if isinstance(df.columns, pd.MultiIndex) else df[['Close']]
        for ticker in all_tickers:
            try:
                if ticker not in close_df.columns:
                    continue
                col = close_df[ticker].dropna()
                if len(col) < 2:
                    continue
                cur = float(col.iloc[-1])
                def pct(n):
                    if len(col) <= n:
                        return None
                    base = float(col.iloc[-1 - n])
                    return round((cur - base) / base * 100, 2) if base else None
                price_data[ticker] = {
                    "price": round(cur, 2),
                    "pct_1d":  pct(1),
                    "pct_1w":  pct(5),
                    "pct_1m":  pct(20),
                }
            except Exception:
                pass
    except Exception:
        pass

    def build_stocks(stock_list):
        result = []
        for sticker, sname in stock_list:
            if sticker in price_data:
                d = price_data[sticker]
                result.append({
                    "ticker": sticker, "name": sname,
                    "price":   d["price"],
                    "pct_1d":  d["pct_1d"],
                    "pct_1w":  d["pct_1w"],
                    "pct_1m":  d["pct_1m"],
                })
        return result

    def sector_pcts(ticker):
        d = price_data.get(ticker, {})
        return d.get("pct_1d"), d.get("pct_1w"), d.get("pct_1m")

    def avg_pcts(stocks):
        def avg(key):
            vals = [s[key] for s in stocks if s.get(key) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None
        return avg("pct_1d"), avg("pct_1w"), avg("pct_1m")

    # 미국 섹터 결과
    us_results = []
    for ticker, name, emoji, us_stocks in us_sector_map:
        if ticker not in price_data:
            continue
        p1d, p1w, p1m = sector_pcts(ticker)
        us_results.append({
            "ticker": ticker, "name": name, "emoji": emoji,
            "price":  price_data[ticker]["price"],
            "pct_1d": p1d, "pct_1w": p1w, "pct_1m": p1m,
            "stocks": build_stocks(us_stocks),
        })

    # 한국 섹터 결과 (종목 평균으로 섹터 수익률 계산)
    kr_results = []
    for name, emoji, kr_stocks in kr_sector_map:
        stocks = build_stocks(kr_stocks)
        if not stocks:
            continue
        p1d, p1w, p1m = avg_pcts(stocks)
        kr_results.append({
            "name": name, "emoji": emoji,
            "pct_1d": p1d, "pct_1w": p1w, "pct_1m": p1m,
            "stocks": stocks,
        })

    return jsonify({
        "us_sectors": us_results,
        "kr_sectors": kr_results,
        "generated_at": datetime.datetime.now().isoformat(),
    })


@app.route('/')
def index():
    """메인 페이지 - 정적 파일 서빙"""
    return send_from_directory(STATIC_DIR, 'index.html')


# ════════════════════════════════════════════
# GitHub 자동 배포 Webhook
# ════════════════════════════════════════════
DEPLOY_SECRET = "stockbot-deploy-2024"

@app.route('/deploy', methods=['POST'])
def deploy():
    """GitHub push → 자동 git pull & 서버 재시작"""
    sig = request.headers.get('X-Hub-Signature-256', '')
    body = request.get_data()
    expected = 'sha256=' + hmac.new(DEPLOY_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 403

    def do_deploy():
        import time
        time.sleep(0.5)
        try:
            subprocess.run(['git', 'pull', 'origin', 'main'], cwd=BASE_DIR, timeout=30)
        except Exception as e:
            print(f"[deploy] git pull error: {e}")
        # run.sh 루프가 서버를 감시하므로 pkill만 하면 자동 재시작됨
        subprocess.Popen(
            'sleep 2 && pkill -f "python3 server.py"',
            shell=True,
            start_new_session=True
        )

    threading.Thread(target=do_deploy, daemon=True).start()
    return jsonify({"status": "배포 시작됨", "message": "git pull 후 서버 재시작 중..."})


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  🚀 멀티마켓 봇 API 서버 시작")
    print(f"  http://localhost:{port}")
    print(f"  /api/signals — 시그널 조회")
    print(f"  /api/run     — 수동 분석 실행")
    print(f"  /api/status  — 서버 상태\n")
    app.run(host='0.0.0.0', port=port, debug=False)
