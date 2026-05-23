#!/usr/bin/env python3
"""
KIS (한국투자증권) Open API 클라이언트
- 환경변수: KIS_APP_KEY, KIS_APP_SECRET, KIS_IS_REAL (1=실전, 미설정=모의)
- 한국 종목(.KS/.KQ)에만 사용
- 토큰 자동 발급 + 파일 캐시 (24시간)
"""

import os, json, time, urllib.request, urllib.parse, urllib.error

_REAL_URL  = "https://openapi.koreainvestment.com:9443"
_PAPER_URL = "https://openapivts.koreainvestment.com:29443"
_TOKEN_FILE = "/tmp/kis_token_cache.json"

_token_cache: dict = {}


def is_available() -> bool:
    return bool(os.environ.get("KIS_APP_KEY") and os.environ.get("KIS_APP_SECRET"))


def _base_url() -> str:
    return _REAL_URL if os.environ.get("KIS_IS_REAL", "").lower() in ("1","true","yes") else _PAPER_URL


def _app_key()    -> str: return os.environ.get("KIS_APP_KEY", "")
def _app_secret() -> str: return os.environ.get("KIS_APP_SECRET", "")


def _get_token() -> str:
    global _token_cache
    now = time.time()

    # 메모리 캐시
    if _token_cache.get("access_token") and now < _token_cache.get("expires_at", 0):
        return _token_cache["access_token"]

    # 파일 캐시
    try:
        if os.path.exists(_TOKEN_FILE):
            with open(_TOKEN_FILE) as f:
                cached = json.load(f)
            if now < cached.get("expires_at", 0):
                _token_cache = cached
                return cached["access_token"]
    except Exception:
        pass

    # 신규 발급
    url  = f"{_base_url()}/oauth2/tokenP"
    body = json.dumps({
        "grant_type": "client_credentials",
        "appkey":     _app_key(),
        "appsecret":  _app_secret(),
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    token   = data["access_token"]
    expires = int(data.get("expires_in", 86400))
    _token_cache = {"access_token": token, "expires_at": now + expires - 300}
    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump(_token_cache, f)
    except Exception:
        pass
    return token


def _get(path: str, tr_id: str, params: dict, timeout: int = 10) -> dict:
    """KIS REST API GET 요청"""
    qs  = urllib.parse.urlencode(params)
    url = f"{_base_url()}{path}?{qs}"
    req = urllib.request.Request(url, headers={
        "authorization": f"Bearer {_get_token()}",
        "appkey":        _app_key(),
        "appsecret":     _app_secret(),
        "tr_id":         tr_id,
        "custtype":      "P",
        "Content-Type":  "application/json; charset=utf-8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


# ──────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────

def get_investor_trend(stock_code: str) -> dict:
    """외국인·기관 최근 5거래일 순매수 동향
    stock_code: '005930' (6자리, .KS/.KQ suffix 제거)
    반환:
        frgn_today: 외국인 당일 순매수량
        frgn_3d   : 외국인 3일 누적 순매수량
        frgn_5d   : 외국인 5일 누적 순매수량
        inst_today: 기관 당일 순매수량
        inst_3d   : 기관 3일 누적 순매수량
        inst_5d   : 기관 5일 누적 순매수량
        signal    : 'strong_buy'|'buy'|'neutral'|'sell'|'strong_sell'
    """
    try:
        resp = _get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": stock_code},
        )
        rows = resp.get("output", [])
        if not rows:
            return {}

        def _int(v):
            try:    return int(str(v).replace(",", "") or 0)
            except: return 0

        frgn = [_int(r.get("frgn_ntby_qty", 0)) for r in rows]
        inst = [_int(r.get("orgn_ntby_qty",  0)) for r in rows]

        frgn_3d = sum(frgn[:3])
        inst_3d = sum(inst[:3])

        # 신호: 외국인 + 기관 동반 방향으로 판정
        if frgn_3d > 0 and inst_3d > 0:
            signal = "strong_buy"
        elif frgn_3d > 0:
            signal = "buy"
        elif frgn_3d < 0 and inst_3d < 0:
            signal = "strong_sell"
        elif frgn_3d < 0:
            signal = "sell"
        else:
            signal = "neutral"

        return {
            "frgn_today": frgn[0] if frgn else 0,
            "frgn_3d":    frgn_3d,
            "frgn_5d":    sum(frgn[:5]),
            "inst_today": inst[0] if inst else 0,
            "inst_3d":    inst_3d,
            "inst_5d":    sum(inst[:5]),
            "signal":     signal,
        }
    except Exception as e:
        return {}


def get_trade_strength(stock_code: str) -> dict:
    """현재가 + 체결강도 (한국 장중 유효)
    반환:
        cttr         : 체결강도 (%) — 50 초과=매수우위, 미만=매도우위
        acml_vol     : 당일 누적 거래량
        prdy_vol     : 전일 거래량
        vol_vs_prev  : 전일 대비 거래량 비율 (1.0=동일)
    """
    try:
        resp = _get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": stock_code},
        )
        out = resp.get("output", {})

        def _f(k):
            try:    return float(str(out.get(k, 0) or 0).replace(",", ""))
            except: return 0.0
        def _i(k):
            try:    return int(str(out.get(k, 0) or 0).replace(",", ""))
            except: return 0

        cttr     = _f("cttr")        # 체결강도 (%)
        acml_vol = _i("acml_vol")    # 당일 누적 거래량
        prdy_vol = _i("prdy_vol")    # 전일 거래량

        return {
            "cttr":        round(cttr, 1),
            "acml_vol":    acml_vol,
            "prdy_vol":    prdy_vol,
            "vol_vs_prev": round(acml_vol / prdy_vol, 2) if prdy_vol else None,
        }
    except Exception:
        return {}
