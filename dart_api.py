#!/usr/bin/env python3
"""
DART (금융감독원 전자공시) Open API 클라이언트
환경변수: DART_API_KEY (또는 DART_KEY)
임원·주요주주 주식 거래, 주요 공시 조회
"""
import os, json, datetime, urllib.request, urllib.parse

_BASE           = "https://opendart.fss.or.kr/api"
_CORP_CACHE_FILE = "/tmp/dart_corp_cache.json"
_corp_cache: dict = {}


def _key() -> str:
    return (os.environ.get("DART_API_KEY")
            or os.environ.get("DART_KEY")
            or os.environ.get("OPENDART_API_KEY", ""))


def is_available() -> bool:
    return bool(_key())


def _get(endpoint: str, params: dict, timeout: int = 10) -> dict:
    p = dict(params)
    p["crtfc_key"] = _key()
    url = f"{_BASE}/{endpoint}?{urllib.parse.urlencode(p)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_corp_code(stock_code: str) -> str:
    """6자리 주식코드 → DART 고유번호(8자리), 캐시 사용"""
    global _corp_cache
    if stock_code in _corp_cache:
        return _corp_cache[stock_code]
    try:
        if os.path.exists(_CORP_CACHE_FILE):
            with open(_CORP_CACHE_FILE) as f:
                cached = json.load(f)
            if stock_code in cached:
                _corp_cache.update(cached)
                return cached[stock_code]
    except Exception:
        pass
    try:
        data = _get("company.json", {"stock_code": stock_code})
        if data.get("status") == "000":
            cc = data.get("corp_code", "")
            if cc:
                _corp_cache[stock_code] = cc
                try:
                    ex = {}
                    if os.path.exists(_CORP_CACHE_FILE):
                        with open(_CORP_CACHE_FILE) as f:
                            ex = json.load(f)
                    ex[stock_code] = cc
                    with open(_CORP_CACHE_FILE, "w") as f:
                        json.dump(ex, f)
                except Exception:
                    pass
                return cc
    except Exception:
        pass
    return ""


def get_insider_trades(stock_code: str, days: int = 60) -> dict:
    """임원·주요주주 주식 거래 내역 (최근 N일)
    반환:
        buy_count : 매수 건수
        sell_count: 매도 건수
        net_signal: 'insider_buy' | 'insider_sell' | 'neutral'
        score_adj : 신뢰도 보정 (+6 매수 우위 / -6 매도 우위)
        details   : [{name, role, trade_type, change, date}, ...]
    """
    corp_code = _get_corp_code(stock_code)
    if not corp_code:
        return {}
    try:
        end_dt = datetime.date.today()
        bgn_dt = end_dt - datetime.timedelta(days=days)
        data = _get("majorstock.json", {
            "corp_code": corp_code,
            "bgn_de":    bgn_dt.strftime("%Y%m%d"),
            "end_de":    end_dt.strftime("%Y%m%d"),
        })
        if data.get("status") != "000":
            return {}
        rows = data.get("list", [])
        buy_count = sell_count = 0
        details = []
        for r in rows:
            raw_chg = str(r.get("vyvl_change", "0") or "0").replace(",", "").replace("+", "").strip()
            try:
                change = int(raw_chg)
            except ValueError:
                change = 0
            is_buy  = change > 0
            is_sell = change < 0
            if is_buy:    buy_count  += 1
            elif is_sell: sell_count += 1
            details.append({
                "name":       r.get("repror_nm", ""),
                "role":       r.get("ofs_at", ""),
                "trade_type": "매수" if is_buy else "매도" if is_sell else "기타",
                "change":     abs(change),
                "date":       (r.get("rcept_dt") or "")[:8],
            })
        if   buy_count > sell_count * 1.5: signal, adj = "insider_buy",  +6
        elif sell_count > buy_count * 1.5: signal, adj = "insider_sell", -6
        else:                              signal, adj = "neutral",        0
        return {
            "buy_count":  buy_count,
            "sell_count": sell_count,
            "net_signal": signal,
            "score_adj":  adj,
            "details":    details[:5],
        }
    except Exception:
        return {}


def get_recent_disclosures(stock_code: str, days: int = 14) -> list:
    """최근 주요 공시 (실적·배당·지분변동·증자 등)"""
    corp_code = _get_corp_code(stock_code)
    if not corp_code:
        return []
    try:
        end_dt = datetime.date.today()
        bgn_dt = end_dt - datetime.timedelta(days=days)
        data = _get("list.json", {
            "corp_code": corp_code,
            "bgn_de":    bgn_dt.strftime("%Y%m%d"),
            "end_de":    end_dt.strftime("%Y%m%d"),
        })
        if data.get("status") != "000":
            return []
        keywords = ["실적", "배당", "유상증자", "지분", "전환사채", "공개매수", "합병", "분할", "취득", "처분", "자사주"]
        result = []
        for r in data.get("list", []):
            title = r.get("report_nm", "")
            if any(kw in title for kw in keywords):
                result.append({"title": title, "date": (r.get("rcept_dt") or "")[:8]})
        return result[:3]
    except Exception:
        return []
