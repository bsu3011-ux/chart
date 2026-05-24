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

import os, json, math, asyncio, datetime, threading, urllib.request, hmac, hashlib, subprocess
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

def _clean(obj):
    """NaN/Infinity → None (JSON 직렬화 안전)"""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj

# ── 봇 임포트 ──
import time
from multi_market_bot_v4 import (
    main as run_bot, MARKETS, load_data, analyze_market, save_json,
    analyze_stock, POPULAR_STOCKS, backtest_strategy, backtest_stock,
)

# ── 절대 경로 기준 설정 ──
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)
CORS(app)  # 모든 도메인 허용

OUTPUT_DIR           = os.environ.get("OUTPUT_DIR", os.path.join(BASE_DIR, "output"))
SIGNALS_FILE         = os.path.join(OUTPUT_DIR, "signals_v4.json")
SIGNAL_HISTORY_FILE  = os.path.join(OUTPUT_DIR, "signal_history.json")
BACKTEST_CACHE_FILE  = os.path.join(OUTPUT_DIR, "backtest_cache_v2.json")  # v2: stop/target 전략 반영
os.makedirs(OUTPUT_DIR,   exist_ok=True)

# ── KRX 전종목 캐시 ──
KRX_CACHE_FILE = os.path.join(OUTPUT_DIR, "krx_stocks.json")
_krx_cache: dict = {}   # ticker → {name, market}

def _load_krx_cache():
    """파일 캐시에서 KRX 전종목 로드"""
    global _krx_cache
    if os.path.exists(KRX_CACHE_FILE):
        try:
            with open(KRX_CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            _krx_cache = data.get("stocks", {})
            return True
        except Exception:
            pass
    return False

def _build_krx_cache():
    """KRX 전종목 목록 수집 (FinanceDataReader → pykrx 순으로 시도)"""
    global _krx_cache
    stocks: dict = {}
    try:
        import FinanceDataReader as fdr
        for market, suffix in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
            df = fdr.StockListing(market)
            code_col  = next((c for c in df.columns if c in ("Code","Symbol","Ticker")), None)
            name_col  = next((c for c in df.columns if c in ("Name","ShortName","CompanyName")), None)
            if code_col is None or name_col is None:
                continue
            for _, row in df.iterrows():
                code = str(row[code_col]).zfill(6)
                name = str(row[name_col])
                stocks[code + suffix] = {"name": name, "market": market, "krx_code": code}
    except Exception as e1:
        print(f"[KRX] FDR 실패: {e1} — pykrx 시도")
        try:
            from pykrx import stock as krx_stock
            import datetime as dt
            today = dt.date.today().strftime("%Y%m%d")
            for market, suffix in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
                try:
                    tickers = krx_stock.get_market_ticker_list(today, market=market)
                except Exception:
                    tickers = krx_stock.get_market_ticker_list(
                        (dt.date.today()-dt.timedelta(days=1)).strftime("%Y%m%d"), market=market)
                for t in tickers:
                    name = krx_stock.get_market_ticker_name(t)
                    stocks[t + suffix] = {"name": name, "market": market, "krx_code": t}
        except Exception as e2:
            print(f"[KRX] pykrx도 실패: {e2}")

    if not stocks:
        print("[KRX] 전종목 캐시 빌드 불가 (네트워크 제한). 6자리 코드 직접 검색은 여전히 작동합니다.")
        return

    _krx_cache = stocks
    with open(KRX_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.datetime.now().isoformat(), "stocks": stocks}, f,
                  ensure_ascii=False)
    print(f"[KRX] 전종목 캐시 완료: {len(stocks)}개")

def _init_krx_cache():
    """서버 시작 시 캐시 로드 (없거나 7일 초과면 백그라운드 갱신)"""
    loaded = _load_krx_cache()
    needs_refresh = True
    if loaded and _krx_cache:
        try:
            with open(KRX_CACHE_FILE, encoding="utf-8") as f:
                meta = json.load(f)
            updated = datetime.datetime.fromisoformat(meta.get("updated", "2000-01-01"))
            age_days = (datetime.datetime.now() - updated).days
            needs_refresh = age_days >= 7
        except Exception:
            needs_refresh = True
    if needs_refresh:
        threading.Thread(target=_build_krx_cache, daemon=True).start()
os.makedirs(STATIC_DIR,   exist_ok=True)

_backtest_mem_cache: dict = {}   # { ticker: {ts, data} }

# ── 텔레그램 설정 (환경변수로 주입) ──
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
        req     = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[telegram] 전송 실패: {e}")
        return False


def _signal_group(signal_type: str) -> str:
    """신호를 3개 그룹으로 분류: buy / neutral / sell"""
    if signal_type in ("STRONG_BUY", "BUY"):
        return "buy"
    if signal_type in ("SELL", "STRONG_SELL", "CASH", "CASH_VOL"):
        return "sell"
    return "neutral"


def _save_signal_history(new_data: dict) -> list:
    """신호 저장 + 그룹 방향 전환 시에만 Telegram 알림. 변경 목록 반환."""
    history = []
    if os.path.exists(SIGNAL_HISTORY_FILE):
        try:
            with open(SIGNAL_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []

    markets = new_data.get("markets", [])
    cur_map = {m["ticker"]: m for m in markets}
    changes = []   # signal_type 변경 (히스토리 기록용)
    alerts  = []   # 그룹 전환 (텔레그램 발송용)

    if history:
        prev_map = {m["ticker"]: m for m in history[-1].get("markets", [])}
        for ticker, m in cur_map.items():
            prev = prev_map.get(ticker, {})
            if not prev:
                continue
            old_type = prev.get("signal_type", "")
            new_type = m.get("signal_type", "")
            if old_type == new_type:
                continue
            change = {
                "ticker":     ticker,
                "name":       m.get("name", ticker),
                "flag":       m.get("flag", ""),
                "old_signal": prev.get("signal", "?"),
                "new_signal": m.get("signal", "?"),
                "price":      m.get("price"),
            }
            changes.append(change)
            # 그룹이 달라질 때만 텔레그램 발송
            if _signal_group(old_type) != _signal_group(new_type):
                alerts.append(change)

    entry = {
        "timestamp": new_data.get("generated_at", datetime.datetime.now().isoformat()),
        "changes":   changes,
        "markets": [{
            "ticker":      m.get("ticker"),
            "name":        m.get("name"),
            "flag":        m.get("flag"),
            "signal_type": m.get("signal_type"),
            "signal":      m.get("signal"),
            "price":       m.get("price"),
            "change_pct":  m.get("change_pct"),
        } for m in markets],
    }
    history.append(entry)
    history = history[-90:]  # 최근 90회 보관

    with open(SIGNAL_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    if alerts:
        ts    = datetime.datetime.now().strftime("%m/%d %H:%M")
        lines = [f"📊 <b>시그널 방향 전환</b> ({ts})"]
        for c in alerts:
            lines.append(f"{c['flag']} {c['name']}: {c['old_signal']} → {c['new_signal']}")
        send_telegram("\n".join(lines))

    return changes


def _run_bot_background():
    """백그라운드에서 봇 분석 → 히스토리 저장 → 텔레그램 알림"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())
        loop.close()
        print("[bot] 분석 완료 → signals_v4.json 갱신")
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            changes = _save_signal_history(data)
            if changes:
                print(f"[bot] 신호 변경 {len(changes)}개 → Telegram 알림 전송")
    except Exception as e:
        print(f"[bot] 분석 오류: {e}")


def _daily_scheduler():
    """매일 오전 8시·오후 4시 (KST = UTC+9) 자동 분석"""
    import time
    run_hours   = {8, 16}
    _last_fired = set()
    while True:
        try:
            kst  = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
            key  = (kst.date(), kst.hour)
            if kst.hour in run_hours and key not in _last_fired:
                _last_fired.add(key)
                # 오래된 key 정리
                today = kst.date()
                _last_fired = {k for k in _last_fired if k[0] >= today}
                print(f"[scheduler] KST {kst.hour}시 자동 분석 시작")
                _run_bot_background()
        except Exception as e:
            print(f"[scheduler] 오류: {e}")
        time.sleep(60)


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


@app.route('/api/signal_history')
def get_signal_history():
    """신호 히스토리 및 변경 이력"""
    if not os.path.exists(SIGNAL_HISTORY_FILE):
        return jsonify({"history": [], "message": "아직 기록이 없습니다"})
    with open(SIGNAL_HISTORY_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)
    return jsonify({"history": history[-30:]})


@app.route('/api/telegram_test')
def telegram_test():
    """텔레그램 연결 테스트"""
    ok = send_telegram("✅ 멀티마켓 봇 텔레그램 연결 테스트 성공!")
    return jsonify({"ok": ok, "token_set": bool(TELEGRAM_TOKEN), "chat_id_set": bool(TELEGRAM_CHAT_ID)})


@app.route('/api/status')
def status():
    """서버 상태 확인"""
    last_updated = None
    if os.path.exists(SIGNALS_FILE):
        mtime = os.path.getmtime(SIGNALS_FILE)
        last_updated = datetime.datetime.fromtimestamp(mtime).isoformat()
    
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=BASE_DIR, text=True
        ).strip()
    except Exception:
        commit = "unknown"

    import kis_api as _ka
    return jsonify({
        "status": "running",
        "version": "4.1",
        "commit": commit,
        "markets": len(MARKETS),
        "last_updated": last_updated,
        "signals_file": SIGNALS_FILE,
        "kis_available": _ka.is_available(),
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
        return jsonify(_clean(result))
    except ValueError:
        # yfinance 실패 → POPULAR_STOCKS 기본 정보 폴백
        basic = POPULAR_STOCKS.get(ticker, {})
        if not basic:
            # 대소문자 변형 탐색
            key = next((k for k in POPULAR_STOCKS if k.upper() == ticker), None)
            basic = POPULAR_STOCKS.get(key, {}) if key else {}
        if basic:
            return jsonify({
                "ticker": ticker,
                "name": basic.get("name", ticker),
                "name_en": basic.get("name_en", ""),
                "sector": basic.get("sector", ""),
                "flag": basic.get("flag", ""),
                "price": None,
                "change_pct": 0,
                "change_abs": 0,
                "signal_type": "NEUTRAL",
                "signal_text": "관망",
                "analysis_text": "실시간 데이터를 불러올 수 없습니다. 서버 네트워크 상태를 확인해주세요.",
                "rsi": None,
                "ma20": None,
                "ma50": None,
                "ma200": None,
                "bb_upper": None,
                "bb_lower": None,
                "support": None,
                "resistance": None,
                "vol_ratio": None,
                "price_history": [],
                "data_unavailable": True,
            })
        return jsonify({"error": f"종목 정보를 찾을 수 없습니다: {ticker}"}), 404
    except Exception as e:
        return jsonify({"error": f"분석 실패: {str(e)}"}), 500


def _yf_lookup_kr_code(code6: str):
    """6자리 KRX 코드 → yfinance로 이름·시장 조회 (.KS 먼저, 실패 시 .KQ)"""
    import yfinance as yf
    for suffix, market in ((".KS", "KOSPI"), (".KQ", "KOSDAQ")):
        ticker = code6 + suffix
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            # fast_info에 last_price가 있으면 유효한 티커
            price = getattr(info, "last_price", None)
            if price and price > 0:
                full_info = t.info
                name = full_info.get("longName") or full_info.get("shortName") or ticker
                return {"ticker": ticker, "name": name, "name_en": name,
                        "sector": market, "flag": "🇰🇷"}
        except Exception:
            pass
    return None


@app.route('/api/search_stocks')
def search_stocks():
    """주식 검색 — POPULAR_STOCKS + KRX 캐시 + 6자리 코드 실시간 조회
    GET /api/search_stocks?q=삼성
    GET /api/search_stocks?q=에스비비
    GET /api/search_stocks?q=389500
    """
    q = request.args.get('q', '').strip().lower()
    results = []
    seen = set()

    # 1) POPULAR_STOCKS 우선 검색 (섹터·영문명 포함)
    for ticker, info in POPULAR_STOCKS.items():
        if not q:
            results.append({"ticker": ticker, **info})
            seen.add(ticker)
        else:
            if (q in ticker.lower()
                    or q in info.get("name", "").lower()
                    or q in info.get("name_en", "").lower()
                    or q in info.get("sector", "").lower()):
                results.append({"ticker": ticker, **info})
                seen.add(ticker)
        if len(results) >= 15:
            break

    # 2) KRX 전종목 캐시에서 추가 검색 (미등록 종목 보완)
    if q and len(results) < 15 and _krx_cache:
        for ticker, info in _krx_cache.items():
            if ticker in seen:
                continue
            name = info.get("name", "")
            krx_code = info.get("krx_code", "")
            if q in ticker.lower() or q in name.lower() or q in krx_code:
                results.append({
                    "ticker": ticker, "name": name, "name_en": "",
                    "sector": info.get("market", ""), "flag": "🇰🇷",
                })
                seen.add(ticker)
            if len(results) >= 15:
                break

    # 3) 6자리 숫자 코드 직접 입력 → yfinance 실시간 조회
    if q and len(results) == 0 and q.isdigit() and len(q) == 6:
        found = _yf_lookup_kr_code(q)
        if found and found["ticker"] not in seen:
            results.append(found)

    return jsonify({"results": results})


@app.route('/api/chart')
def get_chart_data():
    """캔들스틱 차트 데이터 (일봉/주봉/월봉)
    GET /api/chart?ticker=^KS11&interval=1d
    interval: 1d (일봉/2년), 1wk (주봉/5년), 1mo (월봉/전체)
    """
    import yfinance as yf
    import pandas as pd

    ticker   = request.args.get('ticker', '').strip()
    interval = request.args.get('interval', '1d')
    if not ticker:
        return jsonify({"error": "ticker 파라미터 필요"}), 400

    period_map = {'1d': '2y', '1wk': '5y', '1mo': 'max'}
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
    """주요 환율 데이터 — 모두 원화 기준으로 환산"""
    import yfinance as yf
    import pandas as pd

    def fetch(ticker):
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             auto_adjust=True, progress=False, threads=False)
            if df is None or df.empty: return None, None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            cur  = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2]) if len(df) > 1 else cur
            return cur, prev
        except Exception:
            return None, None

    usd_cur, usd_prev = fetch("USDKRW=X")
    if not usd_cur:
        return jsonify({"rates": [], "generated_at": datetime.datetime.now().isoformat()})

    results = []

    def add(key, name, flag, label, krw_cur, krw_prev):
        if krw_cur is None: return
        chg = (krw_cur - krw_prev) / krw_prev * 100 if krw_prev else 0
        dec = 0 if krw_cur >= 10 else 2
        results.append({
            "ticker": key, "name": name, "flag": flag, "label": label,
            "rate": round(krw_cur, dec),
            "change_pct": round(chg, 3),
            "unit": "원",
        })

    # USD: 1달러 = USDKRW원
    add("USDKRW", "USD", "🇺🇸", "1달러", usd_cur, usd_prev)

    # EUR: 1유로 = EURUSD × USDKRW
    eur, eur_p = fetch("EURUSD=X")
    if eur:
        add("EURKRW", "EUR", "🇪🇺", "1유로", eur * usd_cur, eur_p * usd_prev)

    # JPY: 100엔 = (USDKRW / USDJPY) × 100
    jpy, jpy_p = fetch("USDJPY=X")
    if jpy:
        add("JPYKRW", "JPY", "🇯🇵", "100엔", (usd_cur / jpy) * 100, (usd_prev / jpy_p) * 100)

    # GBP: 1파운드 = GBPUSD × USDKRW
    gbp, gbp_p = fetch("GBPUSD=X")
    if gbp:
        add("GBPKRW", "GBP", "🇬🇧", "1파운드", gbp * usd_cur, gbp_p * usd_prev)

    # CNY: 1위안 = USDKRW / USDCNY
    cny, cny_p = fetch("USDCNY=X")
    if cny:
        add("CNYKRW", "CNY", "🇨🇳", "1위안", usd_cur / cny, usd_prev / cny_p)

    # INR: 1루피 = USDKRW / USDINR
    inr, inr_p = fetch("USDINR=X")
    if inr:
        add("INRKRW", "INR", "🇮🇳", "1루피", usd_cur / inr, usd_prev / inr_p)

    # AUD: 1호주달러 = USDKRW / USDAUD  (USDAUD=X: AUD per 1 USD)
    aud, aud_p = fetch("USDAUD=X")
    if aud:
        add("AUDKRW", "AUD", "🇦🇺", "1호주달러", usd_cur / aud, usd_prev / aud_p)

    # BTC: 1BTC = BTC-USD × USDKRW
    btc, btc_p = fetch("BTC-USD")
    if btc:
        add("BTCKRW", "BTC", "₿", "1BTC", btc * usd_cur, btc_p * usd_prev)

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


@app.route('/api/stock_backtest')
def get_stock_backtest():
    """GET /api/stock_backtest?ticker=AAPL
    개별 종목 백테스트 (7일 캐시)."""
    ticker = request.args.get('ticker', '').strip().upper()
    if not ticker:
        return jsonify({"error": "ticker 필요"}), 400
    if ticker.isdigit() and len(ticker) == 6:
        ticker = ticker + ".KS"

    now       = time.time()
    cache_ttl = 7 * 24 * 3600
    cache_key = f"stock_{ticker}"

    mem = _backtest_mem_cache.get(cache_key)
    if mem and now - mem["ts"] < cache_ttl:
        return jsonify(mem["data"])

    try:
        if os.path.exists(BACKTEST_CACHE_FILE):
            with open(BACKTEST_CACHE_FILE, encoding="utf-8") as f:
                file_cache = json.load(f)
            if cache_key in file_cache:
                entry = file_cache[cache_key]
                if now - entry.get("ts", 0) < cache_ttl:
                    _backtest_mem_cache[cache_key] = entry
                    return jsonify(entry["data"])
    except Exception:
        pass

    result = backtest_stock(ticker)
    if result is None:
        return jsonify({"error": "데이터 부족 (최소 1년 이상 상장 종목만 지원)"}), 404

    entry = {"ts": now, "data": result}
    _backtest_mem_cache[cache_key] = entry
    try:
        file_cache = {}
        if os.path.exists(BACKTEST_CACHE_FILE):
            with open(BACKTEST_CACHE_FILE, encoding="utf-8") as f:
                file_cache = json.load(f)
        file_cache[cache_key] = entry
        with open(BACKTEST_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(file_cache, f, ensure_ascii=False)
    except Exception:
        pass

    return jsonify(result)


@app.route('/api/backtest')
def get_backtest():
    """GET /api/backtest?ticker=^KS11
    전략 백테스트 결과 (CAGR, MDD, Sharpe, BnH 비교).
    7일 파일 캐시 → 메모리 캐시 순으로 서빙."""
    ticker = request.args.get('ticker', '').strip()
    if not ticker or ticker not in MARKETS:
        return jsonify({"error": "잘못된 ticker"}), 400

    now      = time.time()
    cache_ttl = 7 * 24 * 3600  # 7일

    # 메모리 캐시 확인
    mem = _backtest_mem_cache.get(ticker)
    if mem and now - mem["ts"] < cache_ttl:
        return jsonify(mem["data"])

    # 파일 캐시 확인
    try:
        if os.path.exists(BACKTEST_CACHE_FILE):
            with open(BACKTEST_CACHE_FILE, encoding="utf-8") as f:
                file_cache = json.load(f)
            if ticker in file_cache:
                entry = file_cache[ticker]
                if now - entry.get("ts", 0) < cache_ttl:
                    _backtest_mem_cache[ticker] = entry
                    return jsonify(entry["data"])
    except Exception:
        pass

    # 백테스트 실행 (yfinance 10y 다운로드 포함, 5~30초 소요)
    result = backtest_strategy(ticker, MARKETS[ticker])
    if result is None:
        return jsonify({"error": "데이터 부족"}), 404

    entry = {"ts": now, "data": result}
    _backtest_mem_cache[ticker] = entry

    try:
        file_cache = {}
        if os.path.exists(BACKTEST_CACHE_FILE):
            with open(BACKTEST_CACHE_FILE, encoding="utf-8") as f:
                file_cache = json.load(f)
        file_cache[ticker] = entry
        with open(BACKTEST_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(file_cache, f, ensure_ascii=False)
    except Exception:
        pass

    return jsonify(result)


RANKING_CACHE_FILE = os.path.join(OUTPUT_DIR, "ranking_cache.json")
_ranking_in_progress = False
_ranking_lock = threading.Lock()


def _analyze_for_ranking(ticker: str):
    """랭킹용 단일 종목 분석 — 실패 시 None"""
    try:
        r = analyze_stock(ticker)
        if r.get("price") is None:
            return None
        info = POPULAR_STOCKS.get(ticker, {})
        krx  = _krx_cache.get(ticker, {})
        is_kr = ticker.endswith(".KS") or ticker.endswith(".KQ")
        return {
            "ticker":     ticker,
            "name":       info.get("name") or krx.get("name") or r.get("name", ticker),
            "name_en":    info.get("name_en", ""),
            "sector":     info.get("sector") or krx.get("market", ""),
            "flag":       info.get("flag") or ("🇰🇷" if is_kr else "🌐"),
            "price":      r.get("price"),
            "change_pct": r.get("change_pct"),
            "confidence": r.get("confidence"),
            "signal_type": r.get("signal_type"),
            "signal_text": r.get("signal_text"),
            "rs_score":   r.get("rs_score"),
            "rs_label":   r.get("rs_label"),
            "mom_1m":     (r.get("momentum") or {}).get("mom_1m"),
            "mom_3m":     (r.get("momentum") or {}).get("mom_3m"),
            "mom_6m":     (r.get("momentum") or {}).get("mom_6m"),
            "regime_label":      (r.get("market_regime") or {}).get("label"),
            "liquidity_label":   (r.get("liquidity") or {}).get("label"),
            "liquidity_tv":      (r.get("liquidity") or {}).get("trading_value_display"),
            "fundamental_label": (r.get("fundamental_score") or {}).get("label"),
            "fundamental_adj":   (r.get("fundamental_score") or {}).get("score_adj"),
            "targets":    r.get("targets"),
            "from_high_pct": r.get("from_high_pct"),
        }
    except Exception:
        return None


def _build_ranking_cache():
    """POPULAR_STOCKS + KRX 전종목(코스피·코스닥) 병렬 분석 → 신뢰도순 캐시 저장"""
    global _ranking_in_progress
    with _ranking_lock:
        if _ranking_in_progress:
            return
        _ranking_in_progress = True

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # POPULAR_STOCKS(미국 포함) + KRX 전종목 합집합 (중복 제거)
        tickers = set(POPULAR_STOCKS.keys())
        if _krx_cache:
            tickers.update(_krx_cache.keys())
        tickers = list(tickers)
        results = []
        print(f"[ranking] 분석 시작: {len(tickers)}개 종목 "
              f"(POPULAR {len(POPULAR_STOCKS)} + KRX {len(_krx_cache)} 합집합)")

        # KRX 전종목 분석은 시간이 오래 걸리므로 워커 수↑, 타임아웃↑
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(_analyze_for_ranking, t): t for t in tickers}
            for fut in as_completed(futures, timeout=1800):
                try:
                    r = fut.result(timeout=45)
                    if r and r.get("confidence") is not None:
                        results.append(r)
                except Exception:
                    pass

        results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        cache = {
            "updated": datetime.datetime.now().isoformat(),
            "total_analyzed": len(results),
            "ranking": results[:200],   # 상위 200개 저장 (전종목 확장)
        }
        with open(RANKING_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_clean(cache), f, ensure_ascii=False)
        print(f"[ranking] 완료: {len(results)}개 분석, 상위 200개 저장")
    except Exception as e:
        print(f"[ranking] 오류: {e}")
    finally:
        _ranking_in_progress = False


@app.route('/api/top_stocks')
def get_top_stocks():
    """신뢰도 기준 종목 랭킹
    GET /api/top_stocks          → 상위 10개
    GET /api/top_stocks?n=20     → 상위 20개
    GET /api/top_stocks?signal=BUY → 매수 신호만
    GET /api/top_stocks?refresh=1  → 강제 재분석
    """
    n             = min(int(request.args.get("n", 10)), 100)
    signal_filter = request.args.get("signal", "")
    refresh       = request.args.get("refresh", "0") == "1"
    cache_ttl     = 7200  # 2시간 (전종목 분석은 5~10분 소요되므로 캐시 수명 연장)

    cache_data = None
    if os.path.exists(RANKING_CACHE_FILE) and not refresh:
        try:
            with open(RANKING_CACHE_FILE, encoding="utf-8") as f:
                cache_data = json.load(f)
            updated  = datetime.datetime.fromisoformat(cache_data["updated"])
            age_sec  = (datetime.datetime.now() - updated).total_seconds()
            if age_sec > cache_ttl:
                cache_data = None
        except Exception:
            cache_data = None

    if cache_data is None or refresh:
        threading.Thread(target=_build_ranking_cache, daemon=True).start()
        if cache_data is None:
            total_count = len(POPULAR_STOCKS) + len(_krx_cache)
            return jsonify({
                "status":  "analyzing",
                "message": f"코스피·코스닥 전종목 포함 {total_count}개 분석 중... (약 5~10분 소요)",
                "ranking": [],
                "total_analyzed": 0,
            })

    ranking = cache_data.get("ranking", [])
    if signal_filter:
        ranking = [r for r in ranking if signal_filter.upper() in (r.get("signal_type") or "")]

    return jsonify({
        "status":         "ok",
        "updated":        cache_data.get("updated"),
        "total_analyzed": cache_data.get("total_analyzed", 0),
        "analyzing":      _ranking_in_progress,
        "ranking":        ranking[:n],
    })


@app.route('/guide')
def guide():
    return send_from_directory(STATIC_DIR, 'guide.html')

@app.route('/countries-110m.json')
def world_map():
    """세계지도 TopoJSON 데이터"""
    return send_from_directory(STATIC_DIR, 'countries-110m.json')


@app.route('/')
def index():
    """메인 페이지 - 정적 파일 서빙 (캐시 방지)"""
    from flask import make_response
    resp = make_response(send_from_directory(STATIC_DIR, 'index.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


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
        # (재시작 후 서버가 뜨면서 _run_bot_background가 자동 실행됨)
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
    print(f"  텔레그램: {'설정됨' if TELEGRAM_TOKEN else '미설정 (TELEGRAM_TOKEN 환경변수 필요)'}\n")
    # 일일 스케줄러 (KST 08:00, 16:00) — 시작 시 자동 분석은 하지 않음
    threading.Thread(target=_daily_scheduler, daemon=True).start()
    # KRX 전종목 캐시 초기화 (없거나 7일 초과면 백그라운드 갱신)
    _init_krx_cache()
    app.run(host='0.0.0.0', port=port, debug=False)
