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

import os, json, asyncio, datetime, threading, urllib.request
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
    """미국 섹터 ETF 히트맵"""
    import yfinance as yf
    import pandas as pd

    sector_map = [
        ("XLK",  "기술",       "💻"),
        ("XLF",  "금융",       "🏦"),
        ("XLV",  "헬스케어",   "🏥"),
        ("XLY",  "경기소비재", "🛍️"),
        ("XLP",  "필수소비재", "🛒"),
        ("XLE",  "에너지",     "⛽"),
        ("XLI",  "산업재",     "🏭"),
        ("XLB",  "소재",       "⚗️"),
        ("XLRE", "리츠",       "🏢"),
        ("XLC",  "통신",       "📡"),
        ("XLU",  "유틸리티",   "⚡"),
    ]
    tickers = [s[0] for s in sector_map]
    results = []
    try:
        df = yf.download(tickers, period="5d", interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            close_df = df['Close']
        else:
            close_df = df[['Close']]

        for ticker, name, emoji in sector_map:
            try:
                col = close_df[ticker].dropna() if ticker in close_df.columns else pd.Series()
                if len(col) < 2: continue
                cur  = float(col.iloc[-1])
                prev = float(col.iloc[-2])
                chg  = (cur - prev) / prev * 100
                results.append({
                    "ticker": ticker, "name": name, "emoji": emoji,
                    "price": round(cur, 2),
                    "change_pct": round(chg, 2),
                })
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({"sectors": results, "generated_at": datetime.datetime.now().isoformat()})


@app.route('/')
def index():
    """메인 페이지 - 정적 파일 서빙"""
    return send_from_directory(STATIC_DIR, 'index.html')


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  🚀 멀티마켓 봇 API 서버 시작")
    print(f"  http://localhost:{port}")
    print(f"  /api/signals — 시그널 조회")
    print(f"  /api/run     — 수동 분석 실행")
    print(f"  /api/status  — 서버 상태\n")
    app.run(host='0.0.0.0', port=port, debug=False)
