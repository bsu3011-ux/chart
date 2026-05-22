"""실시간 뉴스 피드 통합 모듈

3개 소스 통합:
  1) DART OpenAPI  - 공시 (가장 빠름, 5분 이내)
  2) 네이버 금융    - 종목별 뉴스 (5-10분 지연)
  3) 텔레그램 채널  - 한경/매경 등 뉴스봇 (1-3분 지연)

환경변수:
  DART_API_KEY        - https://opendart.fss.or.kr 에서 발급 (무료)
  TELEGRAM_BOT_TOKEN  - @BotFather 에서 생성한 봇 토큰
  TELEGRAM_CHANNELS   - 모니터링할 채널ID 콤마구분 (e.g. "@hankyung_news,@maeknews")

캐시: 메모리 + 5~15분 TTL
"""
from __future__ import annotations
import os, re, time, json, html
import urllib.request, urllib.parse
from datetime import datetime, timedelta
from typing import Optional

# ────────────────────────────────────────────────────────
# 캐시
# ────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, list]] = {}    # key → (expires_at, data)

def _cache_get(key: str):
    v = _cache.get(key)
    if v and v[0] > time.time():
        return v[1]
    return None

def _cache_set(key: str, data: list, ttl_sec: int):
    _cache[key] = (time.time() + ttl_sec, data)

def _http_get(url: str, headers: dict | None = None, timeout: int = 8) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=headers or {
            "User-Agent": "Mozilla/5.0 (compatible; chart-bot/1.0)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


# ────────────────────────────────────────────────────────
# 1) DART OpenAPI - 공시 (가장 빠름)
# ────────────────────────────────────────────────────────
DART_API_KEY = os.environ.get("DART_API_KEY", "")
_dart_corp_cache: dict[str, str] = {}   # ticker(6자리) → corp_code(8자리)
_dart_corp_loaded = False

def _load_dart_corp_codes():
    """DART corp_code 매핑 (한 번만 로드, 메모리 캐시)."""
    global _dart_corp_loaded
    if _dart_corp_loaded or not DART_API_KEY:
        return
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={DART_API_KEY}"
    data = _http_get(url, timeout=15)
    if not data:
        return
    import zipfile, io, xml.etree.ElementTree as ET
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        xml_data = zf.read("CORPCODE.xml").decode("utf-8")
        root = ET.fromstring(xml_data)
        for item in root.findall("list"):
            stk = (item.findtext("stock_code") or "").strip()
            cc  = (item.findtext("corp_code")  or "").strip()
            if stk and cc and len(stk) == 6:
                _dart_corp_cache[stk] = cc
        _dart_corp_loaded = True
    except Exception:
        pass

def dart_disclosures(ticker: str, max_items: int = 10) -> list[dict]:
    """DART 공시 목록.
    ticker: '005930.KS' → 종목코드 005930 추출
    반환: [{title, date, type, url, source}]
    """
    if not DART_API_KEY:
        return []
    # .KS/.KQ 제거, 6자리 코드만 추출
    code = re.sub(r"[^0-9]", "", ticker.split(".")[0])
    if len(code) != 6:
        return []
    cache_key = f"dart_{code}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    _load_dart_corp_codes()
    corp_code = _dart_corp_cache.get(code)
    if not corp_code:
        return []

    today = datetime.now().strftime("%Y%m%d")
    bgn   = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    url = (f"https://opendart.fss.or.kr/api/list.json"
           f"?crtfc_key={DART_API_KEY}&corp_code={corp_code}"
           f"&bgn_de={bgn}&end_de={today}&page_no=1&page_count={max_items}")
    raw = _http_get(url)
    if not raw:
        return []
    try:
        j = json.loads(raw.decode("utf-8"))
    except Exception:
        return []
    if j.get("status") != "000":
        return []
    items = []
    for it in j.get("list", [])[:max_items]:
        rcept_no = it.get("rcept_no", "")
        date = it.get("rcept_dt", "")
        if len(date) == 8:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        items.append({
            "title":  it.get("report_nm", ""),
            "date":   date,
            "type":   it.get("rcept_no_tp", "공시"),
            "url":    f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            "source": "DART",
        })
    _cache_set(cache_key, items, ttl_sec=300)  # 5분
    return items


# ────────────────────────────────────────────────────────
# 2) 네이버 금융 - 종목별 뉴스
# ────────────────────────────────────────────────────────
def naver_news(ticker: str, max_items: int = 10) -> list[dict]:
    """네이버 금융 종목 뉴스 (한국 종목만)."""
    code = re.sub(r"[^0-9]", "", ticker.split(".")[0])
    if len(code) != 6:
        return []
    cache_key = f"naver_{code}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1&sm=title_entity_id.basic&clusterId="
    raw = _http_get(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    f"https://finance.naver.com/item/main.naver?code={code}",
    })
    if not raw:
        return []
    try:
        text = raw.decode("euc-kr", errors="ignore")
    except Exception:
        text = raw.decode("utf-8", errors="ignore")

    # 뉴스 행 파싱: <td class="title"><a href="..." title="...">제목</a></td>
    rows = re.findall(
        r'<a[^>]*href="(/item/news_read\.naver[^"]+)"[^>]*>([^<]+)</a>'
        r'.*?<td class="info">([^<]+)</td>'
        r'.*?<td class="date">([^<]+)</td>',
        text, re.DOTALL,
    )
    items = []
    for href, title, source, date in rows[:max_items]:
        title  = html.unescape(title).strip()
        source = source.strip()
        date   = date.strip()
        if not title:
            continue
        items.append({
            "title":  title,
            "date":   date,
            "type":   "뉴스",
            "url":    "https://finance.naver.com" + href.replace("&amp;", "&"),
            "source": f"네이버({source})",
        })
    _cache_set(cache_key, items, ttl_sec=600)  # 10분
    return items


# ────────────────────────────────────────────────────────
# 3) 텔레그램 채널 - 뉴스봇 메시지
# ────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNELS  = [c.strip() for c in os.environ.get("TELEGRAM_CHANNELS", "").split(",") if c.strip()]
_tg_offset = 0
_tg_buffer: list[dict] = []   # 최근 메시지 누적 버퍼

def _telegram_poll(max_messages: int = 50):
    """텔레그램 봇 updates 폴링. 채널 메시지를 _tg_buffer에 누적."""
    global _tg_offset
    if not TELEGRAM_BOT_TOKEN:
        return
    url = (f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
           f"?offset={_tg_offset}&limit={max_messages}&timeout=0"
           f"&allowed_updates=%5B%22channel_post%22%5D")
    raw = _http_get(url, timeout=5)
    if not raw:
        return
    try:
        j = json.loads(raw.decode("utf-8"))
    except Exception:
        return
    if not j.get("ok"):
        return
    for upd in j.get("result", []):
        _tg_offset = max(_tg_offset, upd.get("update_id", 0) + 1)
        post = upd.get("channel_post") or upd.get("message")
        if not post:
            continue
        chat = post.get("chat", {})
        chan = chat.get("username") or str(chat.get("id", ""))
        text = post.get("text") or post.get("caption", "")
        if not text:
            continue
        _tg_buffer.append({
            "title":  text[:200],
            "full":   text,
            "date":   datetime.fromtimestamp(post.get("date", 0)).strftime("%Y-%m-%d %H:%M"),
            "type":   "텔레그램",
            "url":    f"https://t.me/{chan}/{post.get('message_id', '')}",
            "source": f"TG@{chan}",
            "ts":     post.get("date", 0),
        })
    # 최근 500개만 유지
    if len(_tg_buffer) > 500:
        del _tg_buffer[:-500]

def telegram_news(keyword: str = "", max_items: int = 10) -> list[dict]:
    """텔레그램 버퍼에서 키워드 검색.
    keyword: 종목명·티커 등. 빈 문자열이면 전체 최근 메시지 반환."""
    _telegram_poll()
    kw = (keyword or "").strip().lower()
    if kw:
        matched = [m for m in _tg_buffer if kw in m.get("full", "").lower()]
    else:
        matched = list(_tg_buffer)
    # 최신순
    matched.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return matched[:max_items]


# ────────────────────────────────────────────────────────
# 통합 인터페이스
# ────────────────────────────────────────────────────────
def fetch_news(ticker: str, stock_name: str = "", max_items: int = 15) -> dict:
    """종목별 통합 뉴스 (DART + 네이버 + 텔레그램).
    반환: {"items": [...], "sources": {dart:N, naver:N, telegram:N}, "ticker": ...}
    """
    items: list[dict] = []
    sources = {"dart": 0, "naver": 0, "telegram": 0}

    # 1) DART (한국 종목만)
    try:
        d = dart_disclosures(ticker, max_items=5)
        items.extend(d); sources["dart"] = len(d)
    except Exception:
        pass
    # 2) 네이버 (한국 종목만)
    try:
        n = naver_news(ticker, max_items=8)
        items.extend(n); sources["naver"] = len(n)
    except Exception:
        pass
    # 3) 텔레그램 (종목명·티커 키워드 검색)
    try:
        keywords = []
        if stock_name: keywords.append(stock_name)
        code = re.sub(r"[^0-9]", "", ticker.split(".")[0])
        if len(code) == 6: keywords.append(code)
        tg_items = []
        for kw in keywords:
            tg_items.extend(telegram_news(kw, max_items=5))
        # 중복 제거 (url 기준)
        seen = set(); dedup = []
        for it in tg_items:
            u = it.get("url", "")
            if u and u not in seen:
                seen.add(u); dedup.append(it)
        items.extend(dedup); sources["telegram"] = len(dedup)
    except Exception:
        pass

    # 날짜 내림차순 정렬 (문자열이라도 ISO 형식이면 비교 가능)
    items.sort(key=lambda x: x.get("date", ""), reverse=True)

    return {
        "ticker":   ticker,
        "items":    items[:max_items],
        "sources":  sources,
        "fetched":  datetime.now().isoformat(timespec="seconds"),
    }


def status() -> dict:
    """뉴스 소스 활성화 상태."""
    return {
        "dart":     bool(DART_API_KEY),
        "telegram": bool(TELEGRAM_BOT_TOKEN),
        "channels": TELEGRAM_CHANNELS,
        "naver":    True,
    }
