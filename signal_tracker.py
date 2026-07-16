#!/usr/bin/env python3
"""
신호 정확도 트래커
- BUY/SELL 신호를 기록하고 5 거래일(≥7일) 후 실제 결과를 자동 평가
- 신호 유형별·신뢰도 구간별 적중률 계산
- output/signal_accuracy.json 에 저장
"""
import os, json, datetime, threading

_lock      = threading.Lock()
_DATA_FILE: str = ""


def _init_path():
    global _DATA_FILE
    if not _DATA_FILE:
        base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(base, "output"), exist_ok=True)
        _DATA_FILE = os.path.join(base, "output", "signal_accuracy.json")


def _load() -> dict:
    _init_path()
    try:
        if os.path.exists(_DATA_FILE):
            with open(_DATA_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"signals": [], "last_evaluated": None}


def _save(data: dict):
    _init_path()
    try:
        with open(_DATA_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────────

def record_signal(ticker: str, signal_type: str, confidence: int,
                  price: float, indicators: dict = None,
                  name: str = "") -> str:
    """BUY/SELL 신호 기록 (4시간 이내 동일 종목·신호 중복 제외)
    반환: signal_id (빈 문자열이면 중복·무시됨)
    """
    if signal_type not in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL"):
        return ""

    now = datetime.datetime.utcnow()
    sig_id = f"{ticker}_{now.strftime('%Y%m%d%H%M%S')}"
    cutoff = (now - datetime.timedelta(hours=4)).isoformat()

    with _lock:
        data = _load()
        sigs = data.get("signals", [])

        # 중복 체크
        for s in reversed(sigs[-100:]):
            if (s.get("ticker") == ticker
                    and s.get("signal_type") == signal_type
                    and s.get("timestamp", "") > cutoff):
                return s.get("id", "")

        sigs.append({
            "id":          sig_id,
            "ticker":      ticker,
            "name":        name or ticker,
            "signal_type": signal_type,
            "confidence":  confidence,
            "price":       price,
            "timestamp":   now.isoformat(),
            "indicators":  indicators or {},
            "outcome":     None,
        })
        data["signals"] = sigs[-1000:]   # 최대 1000개
        _save(data)

    return sig_id


def evaluate_pending(max_eval: int = 50) -> int:
    """미평가 신호 결과 자동 계산 (5거래일 단기 + 20거래일 장기)
    - outcome   : 진입 후 5거래일 종가 기준, verdict correct/wrong/neutral (±2%)
    - outcome20 : 진입 후 20거래일 종가 기준 (전략의 실제 보유기간에 가까운 평가)
    반환: 평가된 건수 (5일·20일 합산)
    """
    import yfinance as yf
    import pandas as pd

    now      = datetime.datetime.utcnow()
    cutoff5  = (now - datetime.timedelta(days=7)).isoformat()
    cutoff20 = (now - datetime.timedelta(days=30)).isoformat()

    with _lock:
        data = _load()
        sigs = data.get("signals", [])
        need5  = [s for s in sigs
                  if s.get("outcome") is None
                  and s.get("timestamp", "") <= cutoff5]
        need20 = [s for s in sigs
                  if s.get("outcome20") is None
                  and s.get("timestamp", "") <= cutoff20]
        to_eval = (need5 + [s for s in need20 if s not in need5])[:max_eval]

        if not to_eval:
            return 0

        # ticker별 묶음 처리 (API 요청 최소화)
        by_ticker: dict = {}
        for s in to_eval:
            by_ticker.setdefault(s["ticker"], []).append(s)

        evaluated = 0
        for ticker, entries in by_ticker.items():
            try:
                hist = yf.download(ticker, period="4mo", interval="1d",
                                   auto_adjust=True, progress=False, threads=False)
                if hist is None or hist.empty:
                    continue
                if isinstance(hist.columns, pd.MultiIndex):
                    close = hist["Close"][ticker]
                else:
                    close = hist["Close"]
                close = close.dropna()

                for s in entries:
                    try:
                        entry_dt    = datetime.datetime.fromisoformat(s["timestamp"])
                        entry_price = float(s["price"])
                        future      = close[close.index > entry_dt]
                        is_long = s["signal_type"] in ("BUY", "STRONG_BUY")

                        # ── 5거래일 단기 평가 ──
                        if s.get("outcome") is None and len(future) >= 5:
                            exit_price = float(future.iloc[4])
                            ret        = (exit_price - entry_price) / entry_price * 100
                            if   is_long  and ret >=  2.0: verdict = "correct"
                            elif is_long  and ret <= -2.0: verdict = "wrong"
                            elif not is_long and ret <= -2.0: verdict = "correct"
                            elif not is_long and ret >=  2.0: verdict = "wrong"
                            else:                              verdict = "neutral"
                            s["outcome"] = {
                                "exit_price":  round(exit_price, 2),
                                "return_pct":  round(ret, 2),
                                "verdict":     verdict,
                                "evaluated_at": now.isoformat(),
                            }
                            evaluated += 1

                        # ── 20거래일 장기 평가 (±4% 기준 — 기간에 비례해 완화) ──
                        if s.get("outcome20") is None and len(future) >= 20:
                            exit20 = float(future.iloc[19])
                            ret20  = (exit20 - entry_price) / entry_price * 100
                            if   is_long  and ret20 >=  4.0: v20 = "correct"
                            elif is_long  and ret20 <= -4.0: v20 = "wrong"
                            elif not is_long and ret20 <= -4.0: v20 = "correct"
                            elif not is_long and ret20 >=  4.0: v20 = "wrong"
                            else:                               v20 = "neutral"
                            s["outcome20"] = {
                                "exit_price":  round(exit20, 2),
                                "return_pct":  round(ret20, 2),
                                "verdict":     v20,
                                "evaluated_at": now.isoformat(),
                            }
                            evaluated += 1
                    except Exception:
                        continue
            except Exception:
                continue

        data["last_evaluated"] = now.isoformat()
        _save(data)

    return evaluated


def get_accuracy_stats() -> dict:
    """신호 유형별·신뢰도 구간별 적중률 + 최근 신호 목록"""
    with _lock:
        data = _load()

    sigs = data.get("signals", [])

    # 이름 없는 신호에 POPULAR_STOCKS에서 이름 보충
    try:
        from multi_market_bot_v4 import POPULAR_STOCKS as _ps
        for s in sigs:
            if not s.get("name") or s["name"] == s.get("ticker", ""):
                info = _ps.get(s.get("ticker", ""), {})
                if info.get("name"):
                    s["name"] = info["name"]
    except Exception:
        pass
    evaluated = [s for s in sigs if s.get("outcome") is not None]

    # ── 신호 유형별 ─────────────────────────────────────────────
    by_type: dict = {}
    for s in evaluated:
        st = s["signal_type"]
        if st not in by_type:
            by_type[st] = {"total": 0, "correct": 0, "wrong": 0, "neutral": 0}
        by_type[st]["total"] += 1
        by_type[st][s["outcome"]["verdict"]] += 1

    for st, d in by_type.items():
        t = d["total"]
        d["accuracy"] = round(d["correct"] / t, 3) if t > 0 else 0
        d["avg_return"] = round(
            sum(s["outcome"]["return_pct"] for s in evaluated
                if s["signal_type"] == st) / t, 2
        ) if t > 0 else 0
        # 20거래일 장기 평가 (있는 신호만)
        ev20 = [s for s in evaluated
                if s["signal_type"] == st and s.get("outcome20")]
        if ev20:
            d["total20"]      = len(ev20)
            d["accuracy20"]   = round(sum(1 for s in ev20
                                          if s["outcome20"]["verdict"] == "correct") / len(ev20), 3)
            d["avg_return20"] = round(sum(s["outcome20"]["return_pct"] for s in ev20) / len(ev20), 2)

    # ── 신뢰도 구간별 ────────────────────────────────────────────
    bands_def = [("90-100", 90, 101), ("70-89", 70, 90),
                 ("50-69", 50, 70),  ("0-49",  0,  50)]
    by_band: dict = {}
    for label, lo, hi in bands_def:
        bucket = [s for s in evaluated
                  if lo <= s.get("confidence", 0) < hi]
        t = len(bucket)
        c = sum(1 for s in bucket if s["outcome"]["verdict"] == "correct")
        w = sum(1 for s in bucket if s["outcome"]["verdict"] == "wrong")
        b20 = [s for s in bucket if s.get("outcome20")]
        by_band[label] = {
            "total":    t,
            "correct":  c,
            "wrong":    w,
            "neutral":  t - c - w,
            "accuracy": round(c / t, 3) if t > 0 else None,
            "avg_return": round(
                sum(s["outcome"]["return_pct"] for s in bucket) / t, 2
            ) if t > 0 else None,
            "total20":      len(b20) or None,
            "avg_return20": round(
                sum(s["outcome20"]["return_pct"] for s in b20) / len(b20), 2
            ) if b20 else None,
        }

    # ── 최근 신호 20개 ────────────────────────────────────────────
    recent = sorted(sigs, key=lambda x: x.get("timestamp", ""), reverse=True)[:20]

    # ── 전체 ─────────────────────────────────────────────────────
    total_correct = sum(1 for s in evaluated if s["outcome"]["verdict"] == "correct")
    overall_acc   = round(total_correct / len(evaluated), 3) if evaluated else None

    # ── 임계값 권고 (rolling 20 BUY 신호 기준) ───────────────────
    threshold_hint = None
    recent_buy = [s for s in evaluated
                  if s["signal_type"] in ("BUY","STRONG_BUY")][-20:]
    if len(recent_buy) >= 10:
        acc = sum(1 for s in recent_buy if s["outcome"]["verdict"] == "correct") / len(recent_buy)
        if acc < 0.40:
            threshold_hint = {"action": "raise", "current": 63,
                              "suggested": 68, "reason": f"최근 BUY 적중률 {acc:.0%}로 낮음"}
        elif acc > 0.75:
            threshold_hint = {"action": "ok", "current": 63,
                              "accuracy": f"{acc:.0%}", "reason": "신뢰도 임계값 양호"}

    return {
        "by_type":        by_type,
        "by_band":        by_band,
        "recent":         recent,
        "total":          len(sigs),
        "evaluated":      len(evaluated),
        "pending":        sum(1 for s in sigs if s.get("outcome") is None),
        "overall_acc":    overall_acc,
        "threshold_hint": threshold_hint,
        "last_evaluated": data.get("last_evaluated"),
    }
