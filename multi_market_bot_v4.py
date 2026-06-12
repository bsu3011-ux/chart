#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  멀티마켓 미너비니 + 지수 전략 통합 봇 v4.0
  ─────────────────────────────────────────────────────────
  실데이터 5년 백테스트 검증 완료

  시장별 최적 전략 (BnH 대비 초과수익 확인):
    크립토 BTC/ETH  → 미너비니 추세추종 (MA10/21, Trail ATR×4)
    KOSPI/KOSDAQ    → 레버리지 스위칭 (2x/1x/0x)
    NASDAQ          → 레버리지 스위칭
    S&P500          → 레버리지 스위칭
    NIKKEI/항셍     → 이중필터 모멘텀
    DAX             → 위기방어형

  출력: 텔레그램 알림 + JSON (웹대시보드용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, json, gc, re, asyncio, datetime, warnings
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ════════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ════════════════════════════════════════════════════════════════
# 시장 정의 + 시장별 최적 전략 매핑
# ════════════════════════════════════════════════════════════════
MARKETS = {
    # ── BTC 현물: 레버리지 스위칭 (BITX 2x, MSTR 등) ──
    "BTC-USD": {
        "name": "비트코인", "symbol": "BTC", "flag": "₿",
        "strategy": "leverage",
        "params": {"check_interval":5, "is_crypto":True},
        "period": "1y",
    },
    # ── ETH 현물: 미너비니 타이트 ──
    "ETH-USD": {
        "name": "이더리움", "symbol": "ETH", "flag": "Ξ",
        "strategy": "minervini",
        "params": {"ma_fast":10,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.0,"trailing_atr":3.0,
                   "hard_stop_pct":0.12,"cooldown_days":2},
        "period": "1y",
    },
    # ── SOL: 미너비니 (고변동성 알트, 타이트 스탑) ──
    "SOL-USD": {
        "name": "솔라나", "symbol": "SOL", "flag": "◎",
        "strategy": "minervini",
        "params": {"ma_fast":10,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.2,"trailing_atr":3.5,
                   "hard_stop_pct":0.15,"cooldown_days":2},
        "period": "1y",
    },
    # ── XRP: 미너비니 ──
    "XRP-USD": {
        "name": "리플", "symbol": "XRP", "flag": "✕",
        "strategy": "minervini",
        "params": {"ma_fast":10,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.0,"trailing_atr":3.0,
                   "hard_stop_pct":0.15,"cooldown_days":2},
        "period": "1y",
    },
    # ── BNB: 미너비니 ──
    "BNB-USD": {
        "name": "바이낸스코인", "symbol": "BNB", "flag": "🟡",
        "strategy": "minervini",
        "params": {"ma_fast":10,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.0,"trailing_atr":3.0,
                   "hard_stop_pct":0.12,"cooldown_days":2},
        "period": "1y",
    },
    # ── DOGE: 미너비니 (고변동성, 넓은 스탑) ──
    "DOGE-USD": {
        "name": "도지코인", "symbol": "DOGE", "flag": "🐕",
        "strategy": "minervini",
        "params": {"ma_fast":7,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.5,"trailing_atr":4.0,
                   "hard_stop_pct":0.20,"cooldown_days":2},
        "period": "1y",
    },
    # ── ADA: 미너비니 ──
    "ADA-USD": {
        "name": "에이다", "symbol": "ADA", "flag": "🔵",
        "strategy": "minervini",
        "params": {"ma_fast":10,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.2,"trailing_atr":3.5,
                   "hard_stop_pct":0.15,"cooldown_days":2},
        "period": "1y",
    },
    # ── AVAX: 미너비니 ──
    "AVAX-USD": {
        "name": "아발란체", "symbol": "AVAX", "flag": "🔺",
        "strategy": "minervini",
        "params": {"ma_fast":10,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.2,"trailing_atr":3.5,
                   "hard_stop_pct":0.15,"cooldown_days":2},
        "period": "1y",
    },
    # ── 한국 지수 2x ETF: 레버리지 스위칭 (KOSPI +230%, KOSDAQ +74%) ──
    "^KS11": {
        "name": "KOSPI", "symbol": "KOSPI", "flag": "🇰🇷",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "^KQ11": {
        "name": "KOSDAQ", "symbol": "KOSDAQ", "flag": "🇰🇷",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 미국: 레버리지 (NASDAQ +139%, S&P +67%) ──
    "^GSPC": {
        "name": "S&P 500", "symbol": "SPX", "flag": "🇺🇸",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "^IXIC": {
        "name": "NASDAQ", "symbol": "NDX", "flag": "🇺🇸",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 일본/홍콩: 레버리지 스위칭 (1570.T 2x, YINN 3x) ──
    "^N225": {
        "name": "Nikkei 225", "symbol": "NKI", "flag": "🇯🇵",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "^HSI": {
        "name": "항셍지수", "symbol": "HSI", "flag": "🇭🇰",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 유럽: 레버리지 (LDAX 2x DAX 가능) ──
    "^GDAXI": {
        "name": "DAX", "symbol": "DAX", "flag": "🇩🇪",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 미국: DOW 레버리지 (DDM 2x) ──
    "^DJI": {
        "name": "다우존스", "symbol": "DJI", "flag": "🇺🇸",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 중국: 상해종합 레버리지 (CHAU 2x, YINN 3x) ──
    "000001.SS": {
        "name": "상해종합", "symbol": "SSE", "flag": "🇨🇳",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 중국: 심천성분 레버리지 (YINN 3x) ──
    "399001.SZ": {
        "name": "심천성분", "symbol": "SZSE", "flag": "🇨🇳",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 인도: NIFTY 50 (레버리지 — 강한 성장 시장) ──
    "^NSEI": {
        "name": "NIFTY 50", "symbol": "NIF", "flag": "🇮🇳",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 인도: Sensex (레버리지 — 강한 성장 시장, NIFTY와 동일) ──
    "^BSESN": {
        "name": "Sensex", "symbol": "BSE", "flag": "🇮🇳",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 대만: 가권지수 (레버리지 — TSMC/AI 반도체 사이클, NASDAQ과 동조) ──
    "^TWII": {
        "name": "대만 가권", "symbol": "TWI", "flag": "🇹🇼",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 호주: ASX 200 레버리지 (GEAR 2x) ──
    "^AXJO": {
        "name": "ASX 200", "symbol": "ASX", "flag": "🇦🇺",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 영국: FTSE 100 (위기방어형) ──
    "^FTSE": {
        "name": "FTSE 100", "symbol": "FTSE", "flag": "🇬🇧",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 프랑스: CAC 40 (위기방어형) ──
    "^FCHI": {
        "name": "CAC 40", "symbol": "CAC", "flag": "🇫🇷",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 브라질: Bovespa 레버리지 (BRZU 3x) ──
    "^BVSP": {
        "name": "Bovespa", "symbol": "BVSP", "flag": "🇧🇷",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 싱가포르: STI (위기방어형) ──
    "^STI": {
        "name": "싱가포르 STI", "symbol": "STI", "flag": "🇸🇬",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── VIX: 공포지수 (참조용) ──
    "^VIX": {
        "name": "VIX 공포지수", "symbol": "VIX", "flag": "😱",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "1y",
    },
    # ── 유로 스탁스 50 레버리지 (UPV 2x) ──
    "^STOXX50E": {
        "name": "Euro Stoxx 50", "symbol": "SX5E", "flag": "🇪🇺",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 스위스 SMI ──
    "^SSMI": {
        "name": "Swiss SMI", "symbol": "SMI", "flag": "🇨🇭",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 멕시코 IPC ──
    "^MXX": {
        "name": "Mexico IPC", "symbol": "IPC", "flag": "🇲🇽",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 인도네시아 JKSE ──
    "^JKSE": {
        "name": "Jakarta Comp", "symbol": "JKSE", "flag": "🇮🇩",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 말레이시아 KLCI ──
    "^KLSE": {
        "name": "FTSE KLCI", "symbol": "KLCI", "flag": "🇲🇾",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 뉴질랜드 NZX50 ──
    "^NZ50": {
        "name": "NZX 50", "symbol": "NZ50", "flag": "🇳🇿",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 이스라엘 TA-125 ──
    "^TA125.TA": {
        "name": "Tel Aviv 125", "symbol": "TA125", "flag": "🇮🇱",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 사우디 Tadawul ──
    "^TASI.SR": {
        "name": "Saudi Tadawul", "symbol": "TASI", "flag": "🇸🇦",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 유럽 추가 ──
    "^IBEX": {
        "name": "IBEX 35", "symbol": "IBEX", "flag": "🇪🇸",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "FTSEMIB.MI": {
        "name": "FTSE MIB", "symbol": "MIB", "flag": "🇮🇹",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "^AEX": {
        "name": "AEX", "symbol": "AEX", "flag": "🇳🇱",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "^OMXSPI": {
        "name": "OMX Stockholm", "symbol": "OMX", "flag": "🇸🇪",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "^OSEBX": {
        "name": "Oslo Bors", "symbol": "OBX", "flag": "🇳🇴",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    "^ATX": {
        "name": "ATX", "symbol": "ATX", "flag": "🇦🇹",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 동유럽 / 터키 ──
    "^WIG20": {
        "name": "WIG20", "symbol": "WIG20", "flag": "🇵🇱",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    "XU100.IS": {
        "name": "BIST 100", "symbol": "XU100", "flag": "🇹🇷",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 아프리카 ──
    "^J203.JO": {
        "name": "JSE All Share", "symbol": "JSE", "flag": "🇿🇦",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 동남아 ──
    "^SET.BK": {
        "name": "SET Index", "symbol": "SET", "flag": "🇹🇭",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    "PSEi.PS": {
        "name": "PSEi", "symbol": "PSEi", "flag": "🇵🇭",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 남미 ──
    "^MERV": {
        "name": "MERVAL", "symbol": "MERV", "flag": "🇦🇷",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
}

# ════════════════════════════════════════════════════════════════
# 검색 가능한 인기 주식 목록 (한국 + 미국)
# ════════════════════════════════════════════════════════════════
POPULAR_STOCKS = {
    # ════════════ 한국 KOSPI ════════════
    "005930.KS": {"name": "삼성전자",      "name_en": "Samsung Electronics",  "sector": "반도체",    "flag": "🇰🇷"},
    "000660.KS": {"name": "SK하이닉스",    "name_en": "SK Hynix",             "sector": "반도체",    "flag": "🇰🇷"},
    "005490.KS": {"name": "POSCO홀딩스",   "name_en": "POSCO Holdings",       "sector": "철강",      "flag": "🇰🇷"},
    "035420.KS": {"name": "NAVER",         "name_en": "NAVER",                "sector": "인터넷",    "flag": "🇰🇷"},
    "035720.KS": {"name": "카카오",        "name_en": "Kakao",                "sector": "인터넷",    "flag": "🇰🇷"},
    "207940.KS": {"name": "삼성바이오로직스","name_en":"Samsung Biologics",    "sector": "바이오",    "flag": "🇰🇷"},
    "051910.KS": {"name": "LG화학",        "name_en": "LG Chem",              "sector": "화학",      "flag": "🇰🇷"},
    "006400.KS": {"name": "삼성SDI",       "name_en": "Samsung SDI",          "sector": "배터리",    "flag": "🇰🇷"},
    "068270.KS": {"name": "셀트리온",      "name_en": "Celltrion",            "sector": "바이오",    "flag": "🇰🇷"},
    "105560.KS": {"name": "KB금융",        "name_en": "KB Financial",         "sector": "금융",      "flag": "🇰🇷"},
    "055550.KS": {"name": "신한지주",      "name_en": "Shinhan Financial",    "sector": "금융",      "flag": "🇰🇷"},
    "086790.KS": {"name": "하나금융지주",  "name_en": "Hana Financial",       "sector": "금융",      "flag": "🇰🇷"},
    "003550.KS": {"name": "LG",            "name_en": "LG Corp",              "sector": "지주회사",  "flag": "🇰🇷"},
    "066570.KS": {"name": "LG전자",        "name_en": "LG Electronics",       "sector": "전자",      "flag": "🇰🇷"},
    "011070.KS": {"name": "LG이노텍",      "name_en": "LG Innotek",           "sector": "부품",      "flag": "🇰🇷"},
    "012330.KS": {"name": "현대모비스",    "name_en": "Hyundai Mobis",        "sector": "자동차부품","flag": "🇰🇷"},
    "005380.KS": {"name": "현대자동차",    "name_en": "Hyundai Motor",        "sector": "자동차",    "flag": "🇰🇷"},
    "000270.KS": {"name": "기아",          "name_en": "Kia",                  "sector": "자동차",    "flag": "🇰🇷"},
    "329180.KS": {"name": "HD현대중공업",  "name_en": "HD Hyundai Heavy",     "sector": "조선",      "flag": "🇰🇷"},
    "009540.KS": {"name": "HD한국조선해양","name_en": "HD Korea Shipbuilding", "sector": "조선",      "flag": "🇰🇷"},
    "010130.KS": {"name": "고려아연",      "name_en": "Korea Zinc",           "sector": "비철금속",  "flag": "🇰🇷"},
    "096770.KS": {"name": "SK이노베이션",  "name_en": "SK Innovation",        "sector": "에너지",    "flag": "🇰🇷"},
    "034730.KS": {"name": "SK",            "name_en": "SK Holdings",          "sector": "지주회사",  "flag": "🇰🇷"},
    "030200.KS": {"name": "KT",            "name_en": "KT Corp",              "sector": "통신",      "flag": "🇰🇷"},
    "017670.KS": {"name": "SK텔레콤",      "name_en": "SK Telecom",           "sector": "통신",      "flag": "🇰🇷"},
    "032830.KS": {"name": "삼성생명",      "name_en": "Samsung Life",         "sector": "보험",      "flag": "🇰🇷"},
    "000810.KS": {"name": "삼성화재",      "name_en": "Samsung Fire",         "sector": "보험",      "flag": "🇰🇷"},
    "018260.KS": {"name": "삼성에스디에스","name_en": "Samsung SDS",          "sector": "IT서비스",  "flag": "🇰🇷"},
    "003670.KS": {"name": "포스코퓨처엠",  "name_en": "POSCO Future M",       "sector": "소재",      "flag": "🇰🇷"},
    "028260.KS": {"name": "삼성물산",      "name_en": "Samsung C&T",          "sector": "건설",      "flag": "🇰🇷"},
    "011200.KS": {"name": "HMM",           "name_en": "HMM",                  "sector": "해운",      "flag": "🇰🇷"},
    "009830.KS": {"name": "한화솔루션",    "name_en": "Hanwha Solutions",      "sector": "화학",      "flag": "🇰🇷"},
    "012450.KS": {"name": "한화에어로스페이스","name_en":"Hanwha Aerospace",   "sector": "방산",      "flag": "🇰🇷"},
    "034020.KS": {"name": "두산에너빌리티","name_en": "Doosan Enerbility",    "sector": "에너지",    "flag": "🇰🇷"},
    "015760.KS": {"name": "한국전력",      "name_en": "KEPCO",                "sector": "유틸리티",  "flag": "🇰🇷"},
    "352820.KS": {"name": "하이브",        "name_en": "HYBE",                 "sector": "엔터",      "flag": "🇰🇷"},
    "041510.KS": {"name": "에스엠",        "name_en": "SM Entertainment",     "sector": "엔터",      "flag": "🇰🇷"},
    "259960.KS": {"name": "크래프톤",      "name_en": "KRAFTON",              "sector": "게임",      "flag": "🇰🇷"},
    "036570.KS": {"name": "엔씨소프트",    "name_en": "NCSoft",               "sector": "게임",      "flag": "🇰🇷"},
    "251270.KS": {"name": "넷마블",        "name_en": "Netmarble",            "sector": "게임",      "flag": "🇰🇷"},
    "011170.KS": {"name": "롯데케미칼",    "name_en": "Lotte Chemical",       "sector": "화학",      "flag": "🇰🇷"},
    # ════ 제약 ════
    "000100.KS": {"name": "유한양행",      "name_en": "Yuhan Corp",           "sector": "제약",      "flag": "🇰🇷"},
    "128940.KS": {"name": "한미약품",      "name_en": "Hanmi Pharm",          "sector": "제약",      "flag": "🇰🇷"},
    "170900.KS": {"name": "동아에스티",    "name_en": "Dong-A ST",            "sector": "제약",      "flag": "🇰🇷"},
    "185750.KS": {"name": "종근당",        "name_en": "Chong Kun Dang",       "sector": "제약",      "flag": "🇰🇷"},
    "069620.KS": {"name": "대웅제약",      "name_en": "Daewoong Pharm",       "sector": "제약",      "flag": "🇰🇷"},
    "006280.KS": {"name": "GC녹십자",      "name_en": "GC Biopharma",         "sector": "제약/바이오","flag": "🇰🇷"},
    "003850.KS": {"name": "보령",          "name_en": "Boryung",              "sector": "제약",      "flag": "🇰🇷"},
    "009290.KS": {"name": "광동제약",      "name_en": "Kwangdong Pharm",      "sector": "제약",      "flag": "🇰🇷"},
    "001060.KS": {"name": "JW중외제약",    "name_en": "JW Pharmaceutical",    "sector": "제약",      "flag": "🇰🇷"},
    "000020.KS": {"name": "동화약품",      "name_en": "Dong Wha Pharm",       "sector": "제약",      "flag": "🇰🇷"},
    "008930.KS": {"name": "한미사이언스",  "name_en": "Hanmi Science",        "sector": "제약/지주",  "flag": "🇰🇷"},
    "007570.KS": {"name": "일양약품",      "name_en": "Ilyang Pharm",         "sector": "제약",      "flag": "🇰🇷"},
    "019170.KS": {"name": "신풍제약",      "name_en": "Shinpoong Pharm",      "sector": "제약",      "flag": "🇰🇷"},
    "002390.KS": {"name": "한독",          "name_en": "Handok",               "sector": "제약",      "flag": "🇰🇷"},
    "016580.KS": {"name": "환인제약",      "name_en": "Hwan In Pharm",        "sector": "제약",      "flag": "🇰🇷"},
    "003000.KS": {"name": "부광약품",      "name_en": "Bukwang Pharm",        "sector": "제약",      "flag": "🇰🇷"},
    "002210.KS": {"name": "동성제약",      "name_en": "Dongsung Pharm",       "sector": "제약",      "flag": "🇰🇷"},
    "005500.KS": {"name": "삼진제약",      "name_en": "Samjin Pharm",         "sector": "제약",      "flag": "🇰🇷"},
    "002020.KS": {"name": "코오롱",        "name_en": "Kolon",                "sector": "제약/화학",  "flag": "🇰🇷"},
    "243070.KS": {"name": "휴온스글로벌",  "name_en": "Huons Global",         "sector": "제약",      "flag": "🇰🇷"},
    "373220.KS": {"name": "LG에너지솔루션","name_en": "LG Energy Solution",   "sector": "배터리",    "flag": "🇰🇷"},
    "247540.KS": {"name": "에코프로비엠",  "name_en": "EcoPro BM",            "sector": "소재",      "flag": "🇰🇷"},
    # ════ 전선/전력 테마 ════
    "008260.KS": {"name": "LS",            "name_en": "LS Corp",              "sector": "전선/지주",  "flag": "🇰🇷"},
    "010120.KS": {"name": "LS일렉트릭",   "name_en": "LS Electric",          "sector": "전기/전선",  "flag": "🇰🇷"},
    "001440.KS": {"name": "대한전선",      "name_en": "Taihan Electric Wire", "sector": "전선",       "flag": "🇰🇷"},
    "000500.KS": {"name": "가온전선",      "name_en": "Gaon Cable",           "sector": "전선",       "flag": "🇰🇷"},
    "229640.KS": {"name": "LS에코에너지", "name_en": "LS Eco Energy",        "sector": "전선",       "flag": "🇰🇷"},
    "267260.KS": {"name": "HD현대일렉트릭","name_en": "HD Hyundai Electric",  "sector": "전력기기",   "flag": "🇰🇷"},
    "298040.KS": {"name": "효성중공업",   "name_en": "Hyosung Heavy Ind.",   "sector": "전력기기",   "flag": "🇰🇷"},
    "103140.KS": {"name": "풍산",          "name_en": "Poongsan",             "sector": "비철금속",   "flag": "🇰🇷"},
    "052690.KS": {"name": "한국전력기술", "name_en": "Korea Power Eng.",     "sector": "전력",       "flag": "🇰🇷"},
    "047810.KS": {"name": "한국항공우주", "name_en": "KAI",                  "sector": "방산",       "flag": "🇰🇷"},
    "064350.KS": {"name": "현대로템",      "name_en": "Hyundai Rotem",        "sector": "방산",       "flag": "🇰🇷"},
    "042660.KS": {"name": "한화오션",      "name_en": "Hanwha Ocean",         "sector": "조선",       "flag": "🇰🇷"},
    "010620.KS": {"name": "HD현대미포",   "name_en": "HD Hyundai Mipo",      "sector": "조선",       "flag": "🇰🇷"},
    "042700.KS": {"name": "한미반도체",   "name_en": "Hanmi Semiconductor",  "sector": "반도체장비", "flag": "🇰🇷"},
    "000720.KS": {"name": "현대건설",      "name_en": "Hyundai E&C",          "sector": "건설",       "flag": "🇰🇷"},
    "047040.KS": {"name": "대우건설",      "name_en": "Daewoo E&C",           "sector": "건설",       "flag": "🇰🇷"},
    "316140.KS": {"name": "우리금융지주", "name_en": "Woori Financial",      "sector": "금융",       "flag": "🇰🇷"},
    "032640.KS": {"name": "LG유플러스",   "name_en": "LG Uplus",             "sector": "통신",       "flag": "🇰🇷"},
    "069960.KS": {"name": "현대백화점",   "name_en": "Hyundai Department",   "sector": "유통",       "flag": "🇰🇷"},
    "023530.KS": {"name": "롯데쇼핑",      "name_en": "Lotte Shopping",       "sector": "유통",       "flag": "🇰🇷"},
    "139480.KS": {"name": "이마트",        "name_en": "E-mart",               "sector": "유통",       "flag": "🇰🇷"},
    "078930.KS": {"name": "GS",            "name_en": "GS Holdings",          "sector": "에너지/유통","flag": "🇰🇷"},
    "004170.KS": {"name": "신세계",        "name_en": "Shinsegae",            "sector": "유통",       "flag": "🇰🇷"},
    "241560.KS": {"name": "두산밥캣",      "name_en": "Doosan Bobcat",        "sector": "기계",       "flag": "🇰🇷"},
    # ════════════ 한국 KOSDAQ ════════════
    "086520.KQ": {"name": "에코프로",      "name_en": "EcoPro",               "sector": "소재",      "flag": "🇰🇷"},
    "293490.KQ": {"name": "카카오게임즈",  "name_en": "Kakao Games",          "sector": "게임",      "flag": "🇰🇷"},
    "263750.KQ": {"name": "펄어비스",      "name_en": "Pearl Abyss",          "sector": "게임",      "flag": "🇰🇷"},
    "091990.KQ": {"name": "셀트리온헬스케어","name_en":"Celltrion Healthcare", "sector": "바이오",    "flag": "🇰🇷"},
    "028300.KQ": {"name": "HLB",           "name_en": "HLB",                  "sector": "바이오",    "flag": "🇰🇷"},
    "196170.KQ": {"name": "알테오젠",      "name_en": "Alteogen",             "sector": "바이오",    "flag": "🇰🇷"},
    "214150.KQ": {"name": "클래시스",      "name_en": "Classys",              "sector": "의료기기",  "flag": "🇰🇷"},
    "403870.KQ": {"name": "HPSP",          "name_en": "HPSP",                 "sector": "반도체장비","flag": "🇰🇷"},
    "058470.KQ": {"name": "리노공업",      "name_en": "Leeno Industrial",     "sector": "부품",      "flag": "🇰🇷"},
    "067160.KQ": {"name": "아프리카TV",    "name_en": "AfreecaTV",            "sector": "미디어",    "flag": "🇰🇷"},
    "357780.KQ": {"name": "솔브레인",      "name_en": "Soulbrain",            "sector": "소재",      "flag": "🇰🇷"},
    "039030.KQ": {"name": "이오테크닉스",  "name_en": "EO Technics",          "sector": "레이저",    "flag": "🇰🇷"},
    "131290.KQ": {"name": "티씨케이",      "name_en": "TCI Inc",              "sector": "반도체소재","flag": "🇰🇷"},
    "078340.KQ": {"name": "컴투스",        "name_en": "Com2uS",               "sector": "게임",      "flag": "🇰🇷"},
    "112040.KQ": {"name": "위메이드",      "name_en": "Wemade",               "sector": "게임",      "flag": "🇰🇷"},
    "122870.KQ": {"name": "YG엔터테인먼트","name_en": "YG Entertainment",   "sector": "엔터",      "flag": "🇰🇷"},
    "035900.KQ": {"name": "JYP엔터",      "name_en": "JYP Entertainment",    "sector": "엔터",      "flag": "🇰🇷"},
    "277810.KQ": {"name": "레인보우로보틱스","name_en":"Rainbow Robotics",   "sector": "로봇",      "flag": "🇰🇷"},
    "328130.KQ": {"name": "루닛",          "name_en": "Lunit",               "sector": "AI의료",    "flag": "🇰🇷"},
    "950130.KQ": {"name": "엑스플러스",   "name_en": "Xplus",               "sector": "반도체장비","flag": "🇰🇷"},
    "000990.KS": {"name": "DB하이텍",     "name_en": "DB HiTek",            "sector": "반도체",    "flag": "🇰🇷"},
    "068290.KQ": {"name": "제일전기공업", "name_en": "Jeil Electric",       "sector": "전기기기",  "flag": "🇰🇷"},
    "171090.KQ": {"name": "선익시스템",   "name_en": "Sunic System",         "sector": "OLED장비",  "flag": "🇰🇷"},
    "088130.KQ": {"name": "동아엘텍",     "name_en": "Dong-A Eltek",         "sector": "PCB/전자",  "flag": "🇰🇷"},
    "036930.KQ": {"name": "주성엔지니어링","name_en": "Jusung Engineering",  "sector": "반도체장비","flag": "🇰🇷"},
    "240810.KQ": {"name": "원익IPS",      "name_en": "Wonik IPS",            "sector": "반도체장비","flag": "🇰🇷"},
    "084370.KQ": {"name": "유진테크",     "name_en": "Eugene Technology",    "sector": "반도체장비","flag": "🇰🇷"},
    "319660.KQ": {"name": "피에스케이",   "name_en": "PSK",                  "sector": "반도체장비","flag": "🇰🇷"},
    "056190.KQ": {"name": "에스에프에이", "name_en": "SFA Engineering",      "sector": "FA/디스플레이","flag": "🇰🇷"},
    "007660.KQ": {"name": "이수페타시스", "name_en": "ISU Petasys",          "sector": "PCB",       "flag": "🇰🇷"},
    "183300.KQ": {"name": "코미코",       "name_en": "KOMICO",               "sector": "반도체소재","flag": "🇰🇷"},
    "281820.KQ": {"name": "케이씨텍",     "name_en": "KC Tech",              "sector": "반도체장비","flag": "🇰🇷"},
    "039200.KQ": {"name": "오스코텍",     "name_en": "Oscotec",              "sector": "바이오",    "flag": "🇰🇷"},
    "950160.KQ": {"name": "코오롱티슈진", "name_en": "Kolon TissueGene",    "sector": "바이오",    "flag": "🇰🇷"},
    "041020.KQ": {"name": "폴라리스오피스","name_en": "Polaris Office",      "sector": "소프트웨어","flag": "🇰🇷"},
    "237690.KQ": {"name": "에스티팜",     "name_en": "ST Pharm",             "sector": "CMO",       "flag": "🇰🇷"},
    "065660.KQ": {"name": "에이프로젠",   "name_en": "Aprogen",              "sector": "바이오",    "flag": "🇰🇷"},
    "145020.KQ": {"name": "휴젤",         "name_en": "Hugel",                "sector": "바이오/미용","flag": "🇰🇷"},
    # ════ 코스닥 제약/바이오 추가 ════
    "086900.KQ": {"name": "메디톡스",     "name_en": "Medytox",              "sector": "바이오/미용","flag": "🇰🇷"},
    "108860.KQ": {"name": "셀바스AI",     "name_en": "Selvas AI",            "sector": "AI/헬스",   "flag": "🇰🇷"},
    "214370.KQ": {"name": "케어젠",       "name_en": "Caregen",              "sector": "바이오/미용","flag": "🇰🇷"},
    "016670.KQ": {"name": "신화인터텍",   "name_en": "Shinhwa Intertek",     "sector": "소재",      "flag": "🇰🇷"},
    "115180.KQ": {"name": "큐리언트",     "name_en": "Qurient",              "sector": "바이오",    "flag": "🇰🇷"},
    "187790.KQ": {"name": "레고켐바이오", "name_en": "LegoChem Biosciences", "sector": "바이오",    "flag": "🇰🇷"},
    "255410.KQ": {"name": "에스엔바이오", "name_en": "SN Bioscience",        "sector": "바이오",    "flag": "🇰🇷"},
    "226490.KQ": {"name": "바이오니아",   "name_en": "Bioneer",              "sector": "바이오",    "flag": "🇰🇷"},
    "222980.KQ": {"name": "뉴젠팜",       "name_en": "Newgen Pharm",         "sector": "제약",      "flag": "🇰🇷"},
    "293480.KQ": {"name": "하나제약",     "name_en": "Hana Pharm",           "sector": "제약",      "flag": "🇰🇷"},
    "200130.KQ": {"name": "비씨월드제약", "name_en": "BC World Pharm",       "sector": "제약",      "flag": "🇰🇷"},
    "049630.KQ": {"name": "재원산업",     "name_en": "Jaewon Industrial",    "sector": "제약",      "flag": "🇰🇷"},
    "048870.KQ": {"name": "테스나",       "name_en": "Tesna",                "sector": "반도체검사","flag": "🇰🇷"},
    "079940.KQ": {"name": "가비아",       "name_en": "Gabia",                "sector": "IT인프라",  "flag": "🇰🇷"},
    "357550.KQ": {"name": "득템",         "name_en": "Deoktem",              "sector": "반도체장비","flag": "🇰🇷"},
    "950170.KQ": {"name": "JTC",          "name_en": "JTC",                  "sector": "반도체장비","flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 금융/증권/보험 ════════════
    "006800.KS": {"name": "미래에셋증권",   "name_en": "Mirae Asset Sec.",     "sector": "증권",       "flag": "🇰🇷"},
    "039490.KS": {"name": "키움증권",       "name_en": "Kiwoom Securities",    "sector": "증권",       "flag": "🇰🇷"},
    "016360.KS": {"name": "삼성증권",       "name_en": "Samsung Securities",   "sector": "증권",       "flag": "🇰🇷"},
    "005940.KS": {"name": "NH투자증권",     "name_en": "NH Investment Sec.",   "sector": "증권",       "flag": "🇰🇷"},
    "003540.KS": {"name": "대신증권",       "name_en": "Daeshin Securities",   "sector": "증권",       "flag": "🇰🇷"},
    "071050.KS": {"name": "한국금융지주",   "name_en": "Korea Investment Hld.","sector": "금융",       "flag": "🇰🇷"},
    "138040.KS": {"name": "메리츠금융지주", "name_en": "Meritz Financial",     "sector": "금융",       "flag": "🇰🇷"},
    "175330.KS": {"name": "JB금융지주",     "name_en": "JB Financial",         "sector": "금융",       "flag": "🇰🇷"},
    "139130.KS": {"name": "DGB금융지주",    "name_en": "DGB Financial",        "sector": "금융",       "flag": "🇰🇷"},
    "138930.KS": {"name": "BNK금융지주",    "name_en": "BNK Financial",        "sector": "금융",       "flag": "🇰🇷"},
    "024110.KS": {"name": "기업은행",       "name_en": "IBK",                  "sector": "은행",       "flag": "🇰🇷"},
    "001450.KS": {"name": "현대해상",       "name_en": "Hyundai Marine",       "sector": "보험",       "flag": "🇰🇷"},
    "000060.KS": {"name": "메리츠화재",     "name_en": "Meritz Fire",          "sector": "보험",       "flag": "🇰🇷"},
    "005830.KS": {"name": "DB손해보험",     "name_en": "DB Insurance",         "sector": "보험",       "flag": "🇰🇷"},
    "088350.KS": {"name": "한화생명",       "name_en": "Hanwha Life",          "sector": "보험",       "flag": "🇰🇷"},
    "091170.KS": {"name": "동양생명",       "name_en": "Dongyang Life",        "sector": "보험",       "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 반도체/전자부품 ════════════
    "009150.KS": {"name": "삼성전기",       "name_en": "Samsung Electro-Mech.","sector": "전자부품",   "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 조선/방산 ════════════
    "010140.KS": {"name": "삼성중공업",     "name_en": "Samsung Heavy Ind.",   "sector": "조선",       "flag": "🇰🇷"},
    "079550.KS": {"name": "LIG넥스원",      "name_en": "LIG Nex1",             "sector": "방산",       "flag": "🇰🇷"},
    "272210.KS": {"name": "한화시스템",     "name_en": "Hanwha Systems",       "sector": "방산",       "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 자동차/부품 ════════════
    "161390.KS": {"name": "한국타이어앤테크놀로지","name_en":"Hankook Tire",    "sector": "자동차부품", "flag": "🇰🇷"},
    "002350.KS": {"name": "넥센타이어",     "name_en": "Nexen Tire",           "sector": "자동차부품", "flag": "🇰🇷"},
    "073240.KS": {"name": "금호타이어",     "name_en": "Kumho Tire",           "sector": "자동차부품", "flag": "🇰🇷"},
    "011210.KS": {"name": "현대위아",       "name_en": "Hyundai Wia",          "sector": "자동차부품", "flag": "🇰🇷"},
    "204320.KS": {"name": "만도",           "name_en": "Mando",                "sector": "자동차부품", "flag": "🇰🇷"},
    "018880.KS": {"name": "한온시스템",     "name_en": "Hanon Systems",        "sector": "자동차부품", "flag": "🇰🇷"},
    "042670.KS": {"name": "HD현대인프라코어","name_en":"HD Hyundai Infracore",  "sector": "기계/중장비","flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 항공/운송 ════════════
    "003490.KS": {"name": "대한항공",       "name_en": "Korean Air",           "sector": "항공",       "flag": "🇰🇷"},
    "020560.KS": {"name": "아시아나항공",   "name_en": "Asiana Airlines",      "sector": "항공",       "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 화학/소재 ════════════
    "004020.KS": {"name": "현대제철",       "name_en": "Hyundai Steel",        "sector": "철강",       "flag": "🇰🇷"},
    "011780.KS": {"name": "금호석유화학",   "name_en": "Kumho Petrochemical",  "sector": "화학",       "flag": "🇰🇷"},
    "002380.KS": {"name": "KCC",            "name_en": "KCC Corp",             "sector": "화학/건자재","flag": "🇰🇷"},
    "011790.KS": {"name": "SKC",            "name_en": "SKC",                  "sector": "화학/소재",  "flag": "🇰🇷"},
    "010060.KS": {"name": "OCI",            "name_en": "OCI Holdings",         "sector": "화학",       "flag": "🇰🇷"},
    "120110.KS": {"name": "코오롱인더",     "name_en": "Kolon Industries",     "sector": "화학/섬유",  "flag": "🇰🇷"},
    "298050.KS": {"name": "효성첨단소재",   "name_en": "Hyosung Advanced Mat.","sector": "소재",       "flag": "🇰🇷"},
    "020150.KS": {"name": "롯데에너지머티리얼즈","name_en":"Lotte Energy Mat.", "sector": "배터리소재", "flag": "🇰🇷"},
    "001740.KS": {"name": "SK네트웍스",     "name_en": "SK Networks",          "sector": "유통/서비스","flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 에너지/유틸리티 ════════════
    "010950.KS": {"name": "S-Oil",          "name_en": "S-Oil",                "sector": "에너지",     "flag": "🇰🇷"},
    "036460.KS": {"name": "한국가스공사",   "name_en": "KOGAS",                "sector": "가스",       "flag": "🇰🇷"},
    "112610.KS": {"name": "씨에스윈드",     "name_en": "CS Wind",              "sector": "풍력",       "flag": "🇰🇷"},
    "336260.KS": {"name": "두산퓨얼셀",     "name_en": "Doosan Fuel Cell",     "sector": "수소/연료전지","flag":"🇰🇷"},

    # ════════════ 코스피 추가 — IT/플랫폼/핀테크 ════════════
    "323410.KS": {"name": "카카오뱅크",     "name_en": "KakaoBank",            "sector": "핀테크",     "flag": "🇰🇷"},
    "377300.KS": {"name": "카카오페이",     "name_en": "Kakao Pay",            "sector": "핀테크",     "flag": "🇰🇷"},
    "402340.KS": {"name": "SK스퀘어",       "name_en": "SK Square",            "sector": "IT지주",     "flag": "🇰🇷"},
    "022100.KS": {"name": "포스코DX",       "name_en": "POSCO DX",             "sector": "IT서비스",   "flag": "🇰🇷"},
    "400760.KS": {"name": "현대오토에버",   "name_en": "Hyundai AutoEver",     "sector": "IT서비스",   "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 미디어/엔터/소비재 ════════════
    "035760.KS": {"name": "CJ ENM",         "name_en": "CJ ENM",               "sector": "미디어/엔터","flag": "🇰🇷"},
    "079160.KS": {"name": "CJ CGV",         "name_en": "CJ CGV",               "sector": "영화/엔터",  "flag": "🇰🇷"},
    "033780.KS": {"name": "KT&G",           "name_en": "KT&G",                 "sector": "담배/소비재","flag": "🇰🇷"},
    "021240.KS": {"name": "코웨이",         "name_en": "Coway",                "sector": "생활가전",   "flag": "🇰🇷"},
    "008770.KS": {"name": "호텔신라",       "name_en": "Hotel Shilla",         "sector": "면세/호텔",  "flag": "🇰🇷"},
    "007070.KS": {"name": "GS리테일",       "name_en": "GS Retail",            "sector": "유통",       "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 화장품/뷰티/식품 ════════════
    "090430.KS": {"name": "아모레퍼시픽",   "name_en": "Amorepacific",         "sector": "화장품",     "flag": "🇰🇷"},
    "051900.KS": {"name": "LG생활건강",     "name_en": "LG H&H",               "sector": "소비재",     "flag": "🇰🇷"},
    "192820.KS": {"name": "코스맥스",       "name_en": "Cosmax",               "sector": "화장품OEM",  "flag": "🇰🇷"},
    "161890.KS": {"name": "한국콜마",       "name_en": "Kolmar Korea",         "sector": "화장품OEM",  "flag": "🇰🇷"},
    "097950.KS": {"name": "CJ제일제당",     "name_en": "CJ CheilJedang",       "sector": "식품",       "flag": "🇰🇷"},
    "004370.KS": {"name": "농심",           "name_en": "Nongshim",             "sector": "식품",       "flag": "🇰🇷"},
    "007310.KS": {"name": "오뚜기",         "name_en": "Ottogi",               "sector": "식품",       "flag": "🇰🇷"},
    "005300.KS": {"name": "롯데칠성음료",   "name_en": "Lotte Chilsung",       "sector": "음료",       "flag": "🇰🇷"},
    "000080.KS": {"name": "하이트진로",     "name_en": "Hite Jinro",           "sector": "주류",       "flag": "🇰🇷"},
    "003230.KS": {"name": "삼양식품",       "name_en": "Samyang Foods",        "sector": "식품",       "flag": "🇰🇷"},
    "026960.KS": {"name": "동서",           "name_en": "Dongsuh",              "sector": "식품",       "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 건설/부동산 ════════════
    "006360.KS": {"name": "GS건설",         "name_en": "GS Engineering",       "sector": "건설",       "flag": "🇰🇷"},
    "375500.KS": {"name": "DL이앤씨",       "name_en": "DL E&C",               "sector": "건설",       "flag": "🇰🇷"},
    "294870.KS": {"name": "HDC현대산업개발","name_en": "HDC Hyundai Dev.",     "sector": "건설",       "flag": "🇰🇷"},
    "028050.KS": {"name": "삼성엔지니어링", "name_en": "Samsung Engineering",  "sector": "건설/EPC",   "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 바이오/제약 ════════════
    "302440.KS": {"name": "SK바이오사이언스","name_en":"SK Bioscience",         "sector": "백신/바이오","flag": "🇰🇷"},
    "326030.KS": {"name": "SK바이오팜",     "name_en": "SK Biopharmaceuticals","sector": "제약",       "flag": "🇰🇷"},
    "145720.KS": {"name": "덴티움",         "name_en": "Dentium",              "sector": "의료기기",   "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 로봇/신산업 ════════════
    "454910.KS": {"name": "두산로보틱스",   "name_en": "Doosan Robotics",      "sector": "로봇",       "flag": "🇰🇷"},

    # ════════════ 코스피 추가 — 지주/기타 ════════════
    "004990.KS": {"name": "롯데지주",       "name_en": "Lotte Holdings",       "sector": "지주회사",   "flag": "🇰🇷"},
    "000880.KS": {"name": "한화",           "name_en": "Hanwha Corp",          "sector": "지주회사",   "flag": "🇰🇷"},
    "093050.KS": {"name": "LF",             "name_en": "LF Corp",              "sector": "패션/유통",  "flag": "🇰🇷"},
    "025540.KS": {"name": "한국단자",       "name_en": "Korea Terminals",      "sector": "전자부품",   "flag": "🇰🇷"},
    "004310.KS": {"name": "현대약품",       "name_en": "Hyundai Pharm",        "sector": "제약",       "flag": "🇰🇷"},

    # ════════════ 코스닥 추가 — 반도체/장비/소재 ════════════
    "389500.KQ": {"name": "에스비비테크",   "name_en": "SBB Tech",             "sector": "반도체",     "flag": "🇰🇷"},
    "140860.KQ": {"name": "파크시스템스",   "name_en": "Park Systems",         "sector": "반도체장비", "flag": "🇰🇷"},
    "166090.KQ": {"name": "하나머티리얼즈", "name_en": "Hana Materials",       "sector": "반도체소재", "flag": "🇰🇷"},
    "222800.KQ": {"name": "심텍",           "name_en": "Simtech",              "sector": "반도체기판", "flag": "🇰🇷"},
    "086890.KQ": {"name": "엘비세미콘",     "name_en": "LB Semicon",           "sector": "반도체",     "flag": "🇰🇷"},
    "089030.KQ": {"name": "테크윙",         "name_en": "Techwing",             "sector": "반도체검사", "flag": "🇰🇷"},
    "085870.KQ": {"name": "넥스틴",         "name_en": "Nextin",               "sector": "반도체검사", "flag": "🇰🇷"},
    "095340.KQ": {"name": "ISC",            "name_en": "ISC",                  "sector": "반도체소켓", "flag": "🇰🇷"},
    "014680.KQ": {"name": "한솔케미칼",     "name_en": "Hansol Chemical",      "sector": "반도체소재", "flag": "🇰🇷"},
    "108320.KQ": {"name": "LX세미콘",       "name_en": "LX Semicon",           "sector": "팹리스",     "flag": "🇰🇷"},
    "101490.KQ": {"name": "에스앤에스텍",   "name_en": "SNStek",               "sector": "반도체소재", "flag": "🇰🇷"},
    "054090.KQ": {"name": "에이피시스템",   "name_en": "AP Systems",           "sector": "디스플레이장비","flag":"🇰🇷"},
    "213420.KQ": {"name": "덕산네오룩스",   "name_en": "Duksan Neolux",        "sector": "OLED소재",   "flag": "🇰🇷"},
    "336370.KQ": {"name": "솔루스첨단소재", "name_en": "Solus Advanced Mat.",  "sector": "소재",       "flag": "🇰🇷"},
    "222080.KQ": {"name": "씨아이에스",     "name_en": "CIS",                  "sector": "배터리장비", "flag": "🇰🇷"},
    "090460.KQ": {"name": "비에이치",       "name_en": "BH",                   "sector": "FPCB",       "flag": "🇰🇷"},
    "098460.KQ": {"name": "고영",           "name_en": "Koh Young",            "sector": "검사장비",   "flag": "🇰🇷"},
    "383310.KQ": {"name": "에코프로에이치엔","name_en":"EcoPro HN",             "sector": "소재",       "flag": "🇰🇷"},
    "393890.KQ": {"name": "더블유씨피",     "name_en": "WCP",                  "sector": "배터리소재", "flag": "🇰🇷"},
    "032500.KQ": {"name": "케이엠더블유",   "name_en": "KMW",                  "sector": "통신장비",   "flag": "🇰🇷"},
    "138940.KQ": {"name": "오이솔루션",     "name_en": "OE Solutions",         "sector": "광부품",     "flag": "🇰🇷"},
    "192650.KQ": {"name": "드림텍",         "name_en": "Dreamtech",            "sector": "전자부품",   "flag": "🇰🇷"},
    "189300.KQ": {"name": "제이앤티씨",     "name_en": "JNTC",                 "sector": "유리/부품",  "flag": "🇰🇷"},
    "104830.KQ": {"name": "원익머트리얼즈", "name_en": "Wonik Materials",      "sector": "반도체소재", "flag": "🇰🇷"},
    "102710.KQ": {"name": "이엔에프테크놀로지","name_en":"ENF Technology",      "sector": "반도체소재", "flag": "🇰🇷"},
    "064290.KQ": {"name": "인텍플러스",     "name_en": "Intech Plus",          "sector": "비전검사",   "flag": "🇰🇷"},
    "039440.KQ": {"name": "에스티아이",     "name_en": "STI",                  "sector": "반도체장비", "flag": "🇰🇷"},
    "330350.KQ": {"name": "네패스아크",     "name_en": "Nepes Arc",            "sector": "반도체",     "flag": "🇰🇷"},
    "084850.KQ": {"name": "아이티엠반도체", "name_en": "ITM Semiconductor",    "sector": "배터리부품", "flag": "🇰🇷"},
    "144960.KQ": {"name": "뉴파워프라즈마", "name_en": "New Power Plasma",     "sector": "반도체장비", "flag": "🇰🇷"},

    # ════════════ 코스닥 추가 — 바이오/제약/의료 ════════════
    "096530.KQ": {"name": "씨젠",           "name_en": "Seegene",              "sector": "진단",       "flag": "🇰🇷"},
    "206650.KQ": {"name": "유바이오로직스", "name_en": "EuBiologics",          "sector": "백신",       "flag": "🇰🇷"},
    "298380.KQ": {"name": "에이비엘바이오", "name_en": "ABL Bio",              "sector": "바이오",     "flag": "🇰🇷"},
    "214450.KQ": {"name": "파마리서치",     "name_en": "Pharma Research",      "sector": "바이오/미용","flag": "🇰🇷"},
    "053030.KQ": {"name": "바이넥스",       "name_en": "Binex",                "sector": "CMO",        "flag": "🇰🇷"},
    "138610.KQ": {"name": "나이벡",         "name_en": "Naeovys",              "sector": "바이오",     "flag": "🇰🇷"},
    "009420.KQ": {"name": "제넥신",         "name_en": "Genexine",             "sector": "바이오",     "flag": "🇰🇷"},
    "067630.KQ": {"name": "HLB생명과학",   "name_en": "HLB Life Science",     "sector": "바이오",     "flag": "🇰🇷"},
    "011000.KQ": {"name": "진원생명과학",   "name_en": "Jinwon Bioscience",    "sector": "바이오",     "flag": "🇰🇷"},
    "290650.KQ": {"name": "엘앤씨바이오",   "name_en": "L&C Bio",              "sector": "의료기기",   "flag": "🇰🇷"},
    "115450.KQ": {"name": "지트리비앤티",   "name_en": "G-treeBNT",            "sector": "바이오",     "flag": "🇰🇷"},
    "365270.KQ": {"name": "큐라클",         "name_en": "Curacle",              "sector": "바이오",     "flag": "🇰🇷"},
    "347551.KQ": {"name": "레고켐바이오사이언스","name_en":"LegoChem Biosci.", "sector": "바이오",     "flag": "🇰🇷"},
    "357580.KQ": {"name": "이노테라피",     "name_en": "Innotherapeutics",     "sector": "의료기기",   "flag": "🇰🇷"},
    "340360.KQ": {"name": "제놀루션",       "name_en": "Genolution",           "sector": "진단",       "flag": "🇰🇷"},
    "305090.KQ": {"name": "GI이노베이션",   "name_en": "GI Innovation",        "sector": "바이오",     "flag": "🇰🇷"},
    "378850.KQ": {"name": "CJ바이오사이언스","name_en":"CJ Bioscience",         "sector": "바이오",     "flag": "🇰🇷"},

    # ════════════ 코스닥 추가 — 게임/미디어/엔터 ════════════
    "095660.KQ": {"name": "네오위즈",       "name_en": "Neowiz",               "sector": "게임",       "flag": "🇰🇷"},
    "253450.KQ": {"name": "스튜디오드래곤", "name_en": "Studio Dragon",        "sector": "미디어",     "flag": "🇰🇷"},
    "192080.KQ": {"name": "위메이드맥스",   "name_en": "Wemade Max",           "sector": "게임",       "flag": "🇰🇷"},
    "067000.KQ": {"name": "조이시티",       "name_en": "Joycity",              "sector": "게임",       "flag": "🇰🇷"},

    # ════════════ 코스닥 추가 — 화장품/뷰티 ════════════
    "078520.KQ": {"name": "에이블씨엔씨",   "name_en": "Able C&C",             "sector": "화장품",     "flag": "🇰🇷"},
    "237880.KQ": {"name": "클리오",         "name_en": "Clio Cosmetics",       "sector": "화장품",     "flag": "🇰🇷"},

    # ════════════ 코스닥 추가 — 로봇/AI/소프트웨어 ════════════
    "108490.KQ": {"name": "로보티즈",       "name_en": "Robotis",              "sector": "로봇",       "flag": "🇰🇷"},
    "215200.KQ": {"name": "메가스터디교육", "name_en": "Megastudy Education",  "sector": "교육",       "flag": "🇰🇷"},
    "089600.KQ": {"name": "나스미디어",     "name_en": "Nasmedia",             "sector": "디지털광고", "flag": "🇰🇷"},
    "950190.KQ": {"name": "대양전기공업",   "name_en": "Daeyang Electric",     "sector": "전기기기",   "flag": "🇰🇷"},

    # ════════════ 코스닥 추가 — 에너지/소재 ════════════
    "178320.KQ": {"name": "서진시스템",     "name_en": "Seojin System",        "sector": "에너지저장", "flag": "🇰🇷"},
    "082640.KQ": {"name": "동국씨엠",       "name_en": "Dongkuk C&M",          "sector": "배터리소재", "flag": "🇰🇷"},

    # ════════════ 미국 빅테크 ════════════
    "AAPL":  {"name": "애플",           "name_en": "Apple",              "sector": "Technology",     "flag": "🇺🇸"},
    "MSFT":  {"name": "마이크로소프트", "name_en": "Microsoft",          "sector": "Technology",     "flag": "🇺🇸"},
    "NVDA":  {"name": "엔비디아",       "name_en": "NVIDIA",             "sector": "Semiconductors", "flag": "🇺🇸"},
    "TSLA":  {"name": "테슬라",         "name_en": "Tesla",              "sector": "EV/Auto",        "flag": "🇺🇸"},
    "AMZN":  {"name": "아마존",         "name_en": "Amazon",             "sector": "E-Commerce",     "flag": "🇺🇸"},
    "GOOGL": {"name": "구글",           "name_en": "Alphabet",           "sector": "Internet",       "flag": "🇺🇸"},
    "META":  {"name": "메타",           "name_en": "Meta Platforms",     "sector": "Social Media",   "flag": "🇺🇸"},
    "NFLX":  {"name": "넷플릭스",       "name_en": "Netflix",            "sector": "Streaming",      "flag": "🇺🇸"},
    # ════════════ 미국 반도체 ════════════
    "AMD":   {"name": "AMD",            "name_en": "AMD",                "sector": "Semiconductors", "flag": "🇺🇸"},
    "INTC":  {"name": "인텔",           "name_en": "Intel",              "sector": "Semiconductors", "flag": "🇺🇸"},
    "AVGO":  {"name": "브로드컴",       "name_en": "Broadcom",           "sector": "Semiconductors", "flag": "🇺🇸"},
    "QCOM":  {"name": "퀄컴",           "name_en": "Qualcomm",           "sector": "Semiconductors", "flag": "🇺🇸"},
    "MU":    {"name": "마이크론",       "name_en": "Micron Technology",  "sector": "Semiconductors", "flag": "🇺🇸"},
    "AMAT":  {"name": "어플라이드머티리얼","name_en":"Applied Materials", "sector": "Semiconductor Eq","flag": "🇺🇸"},
    "LRCX":  {"name": "램리서치",       "name_en": "Lam Research",       "sector": "Semiconductor Eq","flag": "🇺🇸"},
    "KLAC":  {"name": "KLA",            "name_en": "KLA Corp",           "sector": "Semiconductor Eq","flag": "🇺🇸"},
    "ASML":  {"name": "ASML",           "name_en": "ASML Holding",       "sector": "Semiconductor Eq","flag": "🇳🇱"},
    "ARM":   {"name": "ARM홀딩스",      "name_en": "ARM Holdings",       "sector": "Semiconductors", "flag": "🇬🇧"},
    "SMCI":  {"name": "슈퍼마이크로",   "name_en": "Super Micro Computer","sector": "Servers",       "flag": "🇺🇸"},
    # ════════════ 미국 소프트웨어/클라우드 ════════════
    "ORCL":  {"name": "오라클",         "name_en": "Oracle",             "sector": "Cloud/DB",       "flag": "🇺🇸"},
    "CRM":   {"name": "세일즈포스",     "name_en": "Salesforce",         "sector": "Cloud/SaaS",     "flag": "🇺🇸"},
    "ADBE":  {"name": "어도비",         "name_en": "Adobe",              "sector": "Software",       "flag": "🇺🇸"},
    "NOW":   {"name": "서비스나우",     "name_en": "ServiceNow",         "sector": "Cloud/SaaS",     "flag": "🇺🇸"},
    "INTU":  {"name": "인튜이트",       "name_en": "Intuit",             "sector": "Fintech/SW",     "flag": "🇺🇸"},
    "IBM":   {"name": "IBM",            "name_en": "IBM",                "sector": "Technology",     "flag": "🇺🇸"},
    "CSCO":  {"name": "시스코",         "name_en": "Cisco",              "sector": "Networking",     "flag": "🇺🇸"},
    "ACN":   {"name": "액센추어",       "name_en": "Accenture",          "sector": "IT Services",    "flag": "🇮🇪"},
    "PLTR":  {"name": "팔란티어",       "name_en": "Palantir",           "sector": "AI/Data",        "flag": "🇺🇸"},
    "SNOW":  {"name": "스노우플레이크", "name_en": "Snowflake",          "sector": "Cloud/Data",     "flag": "🇺🇸"},
    "DDOG":  {"name": "데이터독",       "name_en": "Datadog",            "sector": "Observability",  "flag": "🇺🇸"},
    "CRWD":  {"name": "크라우드스트라이크","name_en":"CrowdStrike",       "sector": "Cybersecurity",  "flag": "🇺🇸"},
    "PANW":  {"name": "팔로알토",       "name_en": "Palo Alto Networks", "sector": "Cybersecurity",  "flag": "🇺🇸"},
    "ZS":    {"name": "지스케일러",     "name_en": "Zscaler",            "sector": "Cybersecurity",  "flag": "🇺🇸"},
    "NET":   {"name": "클라우드플레어", "name_en": "Cloudflare",         "sector": "Networking",     "flag": "🇺🇸"},
    "SHOP":  {"name": "쇼피파이",       "name_en": "Shopify",            "sector": "E-Commerce",     "flag": "🇨🇦"},
    "MSTR":  {"name": "마이크로스트래티지","name_en":"MicroStrategy",    "sector": "Crypto/Software","flag": "🇺🇸"},
    # ════════════ 미국 금융 ════════════
    "V":     {"name": "비자",           "name_en": "Visa",               "sector": "Finance",        "flag": "🇺🇸"},
    "MA":    {"name": "마스터카드",     "name_en": "Mastercard",         "sector": "Finance",        "flag": "🇺🇸"},
    "PYPL":  {"name": "페이팔",         "name_en": "PayPal",             "sector": "Fintech",        "flag": "🇺🇸"},
    "SQ":    {"name": "블록(스퀘어)",   "name_en": "Block (Square)",     "sector": "Fintech",        "flag": "🇺🇸"},
    "JPM":   {"name": "JP모건",         "name_en": "JPMorgan Chase",     "sector": "Banking",        "flag": "🇺🇸"},
    "BAC":   {"name": "뱅크오브아메리카","name_en":"Bank of America",    "sector": "Banking",        "flag": "🇺🇸"},
    "GS":    {"name": "골드만삭스",     "name_en": "Goldman Sachs",      "sector": "Finance",        "flag": "🇺🇸"},
    "MS":    {"name": "모건스탠리",     "name_en": "Morgan Stanley",     "sector": "Finance",        "flag": "🇺🇸"},
    "C":     {"name": "시티그룹",       "name_en": "Citigroup",          "sector": "Banking",        "flag": "🇺🇸"},
    "WFC":   {"name": "웰스파고",       "name_en": "Wells Fargo",        "sector": "Banking",        "flag": "🇺🇸"},
    "BLK":   {"name": "블랙록",         "name_en": "BlackRock",          "sector": "Asset Mgmt",     "flag": "🇺🇸"},
    "AXP":   {"name": "아메리칸익스프레스","name_en":"American Express",  "sector": "Finance",        "flag": "🇺🇸"},
    "COIN":  {"name": "코인베이스",     "name_en": "Coinbase",           "sector": "Crypto",         "flag": "🇺🇸"},
    # ════════════ 미국 헬스케어 ════════════
    "JNJ":   {"name": "존슨앤존슨",     "name_en": "Johnson & Johnson",  "sector": "Healthcare",     "flag": "🇺🇸"},
    "LLY":   {"name": "일라이릴리",     "name_en": "Eli Lilly",          "sector": "Pharma",         "flag": "🇺🇸"},
    "UNH":   {"name": "유나이티드헬스", "name_en": "UnitedHealth",       "sector": "Healthcare",     "flag": "🇺🇸"},
    "ABBV":  {"name": "애브비",         "name_en": "AbbVie",             "sector": "Pharma",         "flag": "🇺🇸"},
    "MRK":   {"name": "머크",           "name_en": "Merck",              "sector": "Pharma",         "flag": "🇺🇸"},
    "PFE":   {"name": "화이자",         "name_en": "Pfizer",             "sector": "Pharma",         "flag": "🇺🇸"},
    "MRNA":  {"name": "모더나",         "name_en": "Moderna",            "sector": "Biotech",        "flag": "🇺🇸"},
    "GILD":  {"name": "길리어드",       "name_en": "Gilead Sciences",    "sector": "Biotech",        "flag": "🇺🇸"},
    "REGN":  {"name": "리제네론",       "name_en": "Regeneron",          "sector": "Biotech",        "flag": "🇺🇸"},
    "VRTX":  {"name": "버텍스",         "name_en": "Vertex Pharma",      "sector": "Biotech",        "flag": "🇺🇸"},
    # ════════════ 미국 소비/유통 ════════════
    "WMT":   {"name": "월마트",         "name_en": "Walmart",            "sector": "Retail",         "flag": "🇺🇸"},
    "COST":  {"name": "코스트코",       "name_en": "Costco",             "sector": "Retail",         "flag": "🇺🇸"},
    "TGT":   {"name": "타겟",           "name_en": "Target",             "sector": "Retail",         "flag": "🇺🇸"},
    "HD":    {"name": "홈디포",         "name_en": "Home Depot",         "sector": "Home Improve",   "flag": "🇺🇸"},
    "NKE":   {"name": "나이키",         "name_en": "Nike",               "sector": "Apparel",        "flag": "🇺🇸"},
    "SBUX":  {"name": "스타벅스",       "name_en": "Starbucks",          "sector": "Restaurant",     "flag": "🇺🇸"},
    "MCD":   {"name": "맥도날드",       "name_en": "McDonald's",         "sector": "Restaurant",     "flag": "🇺🇸"},
    # ════════════ 미국 미디어/엔터 ════════════
    "DIS":   {"name": "디즈니",         "name_en": "Walt Disney",        "sector": "Media/Ent",      "flag": "🇺🇸"},
    "SPOT":  {"name": "스포티파이",     "name_en": "Spotify",            "sector": "Music Streaming","flag": "🇸🇪"},
    "RBLX":  {"name": "로블록스",       "name_en": "Roblox",             "sector": "Gaming/Metaverse","flag":"🇺🇸"},
    "TTWO":  {"name": "테이크투",       "name_en": "Take-Two Interactive","sector": "Gaming",        "flag": "🇺🇸"},
    # ════════════ 미국 에너지/산업 ════════════
    "XOM":   {"name": "엑슨모빌",       "name_en": "ExxonMobil",         "sector": "Energy",         "flag": "🇺🇸"},
    "CVX":   {"name": "쉐브론",         "name_en": "Chevron",            "sector": "Energy",         "flag": "🇺🇸"},
    "CAT":   {"name": "캐터필라",       "name_en": "Caterpillar",        "sector": "Industrial",     "flag": "🇺🇸"},
    "BA":    {"name": "보잉",           "name_en": "Boeing",             "sector": "Aerospace",      "flag": "🇺🇸"},
    "GE":    {"name": "GE에어로스페이스","name_en":"GE Aerospace",       "sector": "Aerospace",      "flag": "🇺🇸"},
    "LMT":   {"name": "록히드마틴",     "name_en": "Lockheed Martin",    "sector": "Defense",        "flag": "🇺🇸"},
    # ════════════ 미국 이동/플랫폼 ════════════
    "UBER":  {"name": "우버",           "name_en": "Uber",               "sector": "Mobility",       "flag": "🇺🇸"},
    "LYFT":  {"name": "리프트",         "name_en": "Lyft",               "sector": "Mobility",       "flag": "🇺🇸"},
    "ABNB":  {"name": "에어비앤비",     "name_en": "Airbnb",             "sector": "Travel/Platform","flag": "🇺🇸"},
    "BKNG":  {"name": "부킹홀딩스",     "name_en": "Booking Holdings",   "sector": "Travel",         "flag": "🇺🇸"},
    "DASH":  {"name": "도어대시",       "name_en": "DoorDash",           "sector": "Delivery",       "flag": "🇺🇸"},
    # ════════════ 미국 주요 ETF ════════════
    "SPY":   {"name": "S&P500 ETF",     "name_en": "SPDR S&P 500 ETF",  "sector": "ETF",            "flag": "🇺🇸"},
    "QQQ":   {"name": "나스닥100 ETF",  "name_en": "Invesco QQQ Trust", "sector": "ETF",            "flag": "🇺🇸"},
    "IWM":   {"name": "러셀2000 ETF",   "name_en": "iShares Russell 2000","sector": "ETF",          "flag": "🇺🇸"},
    "GLD":   {"name": "금 ETF",         "name_en": "SPDR Gold Shares",  "sector": "Commodity ETF",  "flag": "🌏"},
    "SLV":   {"name": "은 ETF",         "name_en": "iShares Silver Trust","sector": "Commodity ETF", "flag": "🌏"},
    "TLT":   {"name": "미국채 20년 ETF","name_en": "iShares 20Y+ Treasury","sector": "Bond ETF",    "flag": "🇺🇸"},
    "SOXL":  {"name": "반도체 3배 ETF", "name_en": "Direxion Semi Bull 3x","sector": "Leveraged ETF","flag":"🇺🇸"},
    "TQQQ":  {"name": "나스닥 3배 ETF", "name_en": "ProShares UltraPro QQQ","sector": "Leveraged ETF","flag":"🇺🇸"},
    # ════════════ 크립토 ════════════
    "BTC-USD":  {"name": "비트코인",    "name_en": "Bitcoin",            "sector": "Crypto L1",      "flag": "₿"},
    "ETH-USD":  {"name": "이더리움",    "name_en": "Ethereum",           "sector": "Crypto L1",      "flag": "Ξ"},
    "SOL-USD":  {"name": "솔라나",      "name_en": "Solana",             "sector": "Crypto L1",      "flag": "◎"},
    "BNB-USD":  {"name": "바이낸스코인","name_en": "Binance Coin",       "sector": "Crypto Exchange","flag": "🔶"},
    "XRP-USD":  {"name": "리플",        "name_en": "Ripple XRP",         "sector": "Crypto Payment", "flag": "🔵"},
    "DOGE-USD": {"name": "도지코인",    "name_en": "Dogecoin",           "sector": "Meme Coin",      "flag": "🐶"},
    "ADA-USD":  {"name": "에이다",      "name_en": "Cardano ADA",        "sector": "Crypto L1",      "flag": "🔷"},
    "AVAX-USD": {"name": "아발란체",    "name_en": "Avalanche AVAX",     "sector": "Crypto L1",      "flag": "🔺"},
    # ════════════ 중국 ADR ════════════
    "BABA":  {"name": "알리바바",       "name_en": "Alibaba Group",      "sector": "E-Commerce",     "flag": "🇨🇳"},
    "TCEHY": {"name": "텐센트",         "name_en": "Tencent Holdings",   "sector": "Internet",       "flag": "🇨🇳"},
    "PDD":   {"name": "핀둬둬",         "name_en": "PDD Holdings",       "sector": "E-Commerce",     "flag": "🇨🇳"},
    "JD":    {"name": "징동닷컴",       "name_en": "JD.com",             "sector": "E-Commerce",     "flag": "🇨🇳"},
    "BIDU":  {"name": "바이두",         "name_en": "Baidu",              "sector": "Internet/AI",    "flag": "🇨🇳"},
    "NIO":   {"name": "니오",           "name_en": "NIO",                "sector": "EV",             "flag": "🇨🇳"},
    "XPEV":  {"name": "샤오펑",         "name_en": "XPeng",              "sector": "EV",             "flag": "🇨🇳"},
    "LI":    {"name": "리오토",         "name_en": "Li Auto",            "sector": "EV",             "flag": "🇨🇳"},
    # ════════════ 일본 ════════════
    "7203.T": {"name": "토요타",        "name_en": "Toyota Motor",       "sector": "Automotive",     "flag": "🇯🇵"},
    "6758.T": {"name": "소니",          "name_en": "Sony Group",         "sector": "Electronics",    "flag": "🇯🇵"},
    "9984.T": {"name": "소프트뱅크",    "name_en": "SoftBank Group",     "sector": "Telecom/VC",     "flag": "🇯🇵"},
    "6861.T": {"name": "키엔스",        "name_en": "Keyence",            "sector": "FA/Sensor",      "flag": "🇯🇵"},
    "8035.T": {"name": "도쿄일렉트론",  "name_en": "Tokyo Electron",     "sector": "Semiconductor Eq","flag": "🇯🇵"},
    "7974.T": {"name": "닌텐도",        "name_en": "Nintendo",           "sector": "Gaming",         "flag": "🇯🇵"},
    "4519.T": {"name": "주가이제약",    "name_en": "Chugai Pharma",      "sector": "Pharma",         "flag": "🇯🇵"},
}


# ════════════════════════════════════════════════════════════════
# 공통 지표
# ════════════════════════════════════════════════════════════════
def calc_rsi(c, p=14):
    d=c.diff(); g=d.clip(lower=0).rolling(p).mean(); l=(-d.clip(upper=0)).rolling(p).mean()
    return 100-(100/(1+g/l.replace(0,float('nan'))))

def calc_atr(df, p=14):
    h,l,c=df['High'],df['Low'],df['Close'].shift(1)
    return pd.concat([h-l,(h-c).abs(),(l-c).abs()],axis=1).max(axis=1).rolling(p).mean()

def calc_macd(close, fast=12, slow=26, signal=9):
    """MACD 라인, 시그널 라인, 히스토그램 반환"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig  = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return float(macd.iloc[-1]), float(sig.iloc[-1]), float(hist.iloc[-1])

def calc_bollinger(close, period=20, std_dev=2):
    """볼린저밴드 (upper, mid, lower, %B, bandwidth) 반환"""
    ma  = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper  = ma + std_dev * std
    lower  = ma - std_dev * std
    cur    = float(close.iloc[-1])
    _u, _m, _l = float(upper.iloc[-1]), float(ma.iloc[-1]), float(lower.iloc[-1])
    pct_b  = (cur - _l) / (_u - _l) if (_u - _l) > 0 else 0.5
    bw     = (_u - _l) / _m * 100 if _m > 0 else 0
    return _u, _m, _l, round(pct_b, 3), round(bw, 2)

def calc_volume_analysis(df):
    """거래량 분석: (vol_ratio, is_spike, trend) 반환"""
    vol    = df['Volume']
    avg20  = float(vol.rolling(20).mean().iloc[-1])
    avg60  = float(vol.rolling(60).mean().iloc[-1])
    cur    = float(vol.iloc[-1])
    ratio  = cur / avg20 if avg20 > 0 else 1.0
    spike  = ratio > 1.5
    trend  = "증가" if avg20 > avg60 else "감소"
    return round(ratio, 2), spike, trend


def detect_rsi_divergence(close, rsi_series, lookback=20):
    """RSI 다이버전스 감지
    Bullish: 가격은 새 저점이지만 RSI는 더 높은 저점 (반등 신호)
    Bearish: 가격은 새 고점이지만 RSI는 더 낮은 고점 (반전 신호)
    반환: 'bullish', 'bearish', or None
    """
    if len(close) < lookback * 2:
        return None
    recent_price = close.iloc[-lookback:]
    recent_rsi   = rsi_series.iloc[-lookback:].dropna()
    prev_price   = close.iloc[-lookback*2:-lookback]
    prev_rsi     = rsi_series.iloc[-lookback*2:-lookback].dropna()
    if recent_rsi.empty or prev_rsi.empty:
        return None
    # 가격 신저점인데 RSI는 더 높은 저점
    if recent_price.min() < prev_price.min() and recent_rsi.min() > prev_rsi.min() + 2:
        return "bullish"
    # 가격 신고점인데 RSI는 더 낮은 고점
    if recent_price.max() > prev_price.max() and recent_rsi.max() < prev_rsi.max() - 2:
        return "bearish"
    return None


def detect_candle_pattern(df):
    """최근 1~2봉 주요 캔들 패턴 감지. 반환: 패턴명 or None"""
    if len(df) < 3: return None
    o1, h1, l1, c1 = float(df['Open'].iloc[-1]), float(df['High'].iloc[-1]), float(df['Low'].iloc[-1]), float(df['Close'].iloc[-1])
    o2, h2, l2, c2 = float(df['Open'].iloc[-2]), float(df['High'].iloc[-2]), float(df['Low'].iloc[-2]), float(df['Close'].iloc[-2])
    body1, range1 = abs(c1 - o1), max(h1 - l1, 1e-9)
    body2, range2 = abs(c2 - o2), max(h2 - l2, 1e-9)
    upper_wick1 = h1 - max(c1, o1)
    lower_wick1 = min(c1, o1) - l1

    # 강세형 장악 (Bullish Engulfing)
    if c2 < o2 and c1 > o1 and c1 >= o2 and o1 <= c2 and body1 > body2 * 0.8:
        return "강세 장악형"
    # 약세형 장악 (Bearish Engulfing)
    if c2 > o2 and c1 < o1 and o1 >= c2 and c1 <= o2 and body1 > body2 * 0.8:
        return "약세 장악형"
    # 해머 (Hammer) — 하락추세 끝에서 반전 신호
    if lower_wick1 > body1 * 2 and upper_wick1 < body1 * 0.3 and body1 / range1 < 0.4:
        return "해머 (저점 반전)"
    # 슈팅스타 (Shooting Star)
    if upper_wick1 > body1 * 2 and lower_wick1 < body1 * 0.3 and body1 / range1 < 0.4:
        return "슈팅스타 (고점 반전)"
    # 도지 (Doji) — 매수·매도 균형
    if body1 / range1 < 0.1:
        return "도지 (방향 결정 임박)"
    return None


def calc_position_targets(price, atr_val, support, resistance, signal_type,
                           ma20=None, ma50=None, low_10d=None, high_10d=None):
    """손절가·목표가·R:R 계산 (기술적 지지/저항 + ATR 기반)

    손절 우선순위 (매수):
      1) 10일 스윙로우 + ATR×0.2 버퍼
      2) 20일 지지선 + ATR×0.2 버퍼
      3) MA20 - ATR×0.3
      4) MA50 - ATR×0.3
      5) 폴백: 현재가 - ATR×2
      → ATR×0.8 ~ ATR×3 범위로 클램핑

    손절 우선순위 (매도):
      1) 10일 스윙하이 + ATR×0.2 버퍼
      2) 20일 저항선 + ATR×0.2 버퍼
      3) MA20 + ATR×0.3 (MA20이 현재가 위일 때)
      4) MA50 + ATR×0.3 (MA50이 현재가 위일 때)
      5) 폴백: 현재가 + ATR×1.5
      → ATR×0.5 ~ ATR×3 범위로 클램핑

    목표 (신호 강도 반응):
      STRONG_BUY/STRONG_SELL = 3.5R / BUY/SELL = 3.0R
      T1 = 1.5R (1차 부분익절)
      T2 = 메인 목표

    NEUTRAL/CASH 등 방향 없는 시그널은 None 반환.
    """
    if not atr_val or atr_val <= 0 or price <= 0:
        return None

    LONG_SIGNALS  = {"STRONG_BUY", "BUY", "LEVERAGE_2X", "HOLD_1X", "INVESTED"}
    SHORT_SIGNALS = {"STRONG_SELL", "SELL"}
    is_long  = signal_type in LONG_SIGNALS
    is_short = signal_type in SHORT_SIGNALS
    if not is_long and not is_short:
        return None  # NEUTRAL/CASH 등 비방향 시그널 — 진입 전략 없음

    # 신호 강도 → 목표 배수
    mult = {"STRONG_BUY": 3.5, "BUY": 3.0}.get(signal_type, 2.5) if is_long \
      else {"STRONG_SELL": 3.5, "SELL": 3.0}.get(signal_type, 2.5)

    if is_long:
        # ── 손절 후보 ──
        cands = []
        if low_10d  and low_10d  < price: cands.append(low_10d  - atr_val * 0.2)
        if support  and support  < price: cands.append(support  - atr_val * 0.2)
        if ma20     and ma20     < price: cands.append(ma20     - atr_val * 0.3)
        if ma50     and ma50     < price: cands.append(ma50     - atr_val * 0.3)
        # ATR×0.8 ~ ATR×3 사이의 후보만 유효
        valid = [c for c in cands if atr_val * 0.8 < price - c < atr_val * 3.0]
        stop = max(valid) if valid else price - atr_val * 2.0  # 가장 가까운 유효 지지선
        # 클램핑
        stop = max(stop, price - atr_val * 3.0)
        stop = min(stop, price - atr_val * 0.8)

        risk = price - stop
        if risk <= 0: return None

        # ── 목표가 ──
        t1     = price + risk * 1.5
        t2_base= price + risk * mult
        # 저항선이 현재가 1% 이상 위이고 T2 기본값 아래 있으면 t2에 반영
        if resistance and resistance > price * 1.01:
            t2 = max(t2_base, min(resistance, price + risk * 5))
        else:
            t2 = t2_base

        reward = t2 - price
        rr     = round(reward / risk, 2) if risk > 0 else 0
        target = t2

    else:  # 매도 시그널
        cands = []
        if high_10d  and high_10d  > price: cands.append(high_10d  + atr_val * 0.2)
        if resistance and resistance > price: cands.append(resistance + atr_val * 0.2)
        if ma20 and ma20 > price: cands.append(ma20 + atr_val * 0.3)
        if ma50 and ma50 > price: cands.append(ma50 + atr_val * 0.3)
        # 유효 범위: ATR×0.5 ~ ATR×3 (롱보다 하한 완화 — 주가 위 저항이 가까울 수 있음)
        valid = [c for c in cands if atr_val * 0.5 < c - price < atr_val * 3.0]
        stop = min(valid) if valid else price + atr_val * 1.5  # 폴백 ATR×2→ATR×1.5
        stop = min(stop, price + atr_val * 3.0)
        stop = max(stop, price + atr_val * 0.5)

        risk = stop - price
        if risk <= 0: return None

        t1     = price - risk * 1.5
        t2_base= price - risk * mult
        if support and support < price * 0.99:
            t2 = min(t2_base, max(support, price - risk * 5))
        else:
            t2 = t2_base

        reward = price - t2
        rr     = round(reward / risk, 2) if risk > 0 else 0
        target = t2

    return {
        "stop":        round(stop,   2),
        "target":      round(target, 2),
        "t1":          round(t1,     2),
        "t2":          round(t2,     2),
        "rr":          max(0, rr),
        "is_long":     is_long,
        "risk_pct":    round(abs(price - stop)   / price * 100, 2),
        "reward_pct":  round(abs(target - price) / price * 100, 2),
        # 목표 방향 표시용 부호 (롱=+, 숏=-)
        "t1_pct":      round((t1 - price) / price * 100, 2),
        "t2_pct":      round((t2 - price) / price * 100, 2),
    }


def calc_position_size(price, stop, account_size=10_000_000, risk_pct=1.0):
    """1% 룰 기반 포지션 사이즈 계산
    risk_pct: 계좌 대비 손실 허용 % (기본 1%)
    반환: 권장 매수 수량, 투자금액"""
    if not stop or price <= 0:
        return None
    risk_per_share = abs(price - stop)
    if risk_per_share <= 0:
        return None
    max_loss = account_size * (risk_pct / 100)
    shares = int(max_loss / risk_per_share)
    # 타이트한 손절(0.5% 등)일 때 투자금이 계좌를 초과(레버리지)하던 버그 → 계좌 한도 캡
    max_affordable = int(account_size / price) if price > 0 else 0
    capped = shares > max_affordable
    shares = min(shares, max_affordable)
    invest = shares * price
    return {
        "shares":      shares,
        "invest":      int(invest),
        "invest_pct":  round(invest / account_size * 100, 1),
        "max_loss":    int(min(max_loss, shares * risk_per_share)),
        "account":     account_size,
        "risk_pct":    risk_pct,
        "capped":      capped,   # True면 계좌 한도로 수량 제한됨 (실효 리스크 < risk_pct)
    }


def calc_adx(df, period=14):
    """ADX 추세강도 지표 (0-100, >25=강한 추세, <20=횡보)"""
    h, l, c = df['High'], df['Low'], df['Close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    plus_dm  = (h.diff()).where((h.diff() > l.diff().abs()) & (h.diff() > 0), 0)
    minus_dm = (l.diff().abs()).where((l.diff().abs() > h.diff()) & (l.diff() < 0), 0)
    atr = tr.rolling(period).mean()
    plus_di  = 100 * (plus_dm.rolling(period).mean() / atr.replace(0, float('nan')))
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr.replace(0, float('nan')))
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float('nan'))
    adx = dx.rolling(period).mean()
    return adx, plus_di, minus_di


def calc_stochastic(df, k_period=14, d_period=3):
    """스토캐스틱 %K, %D (0-100, >80=과매수, <20=과매도)"""
    low_min  = df['Low'].rolling(k_period).min()
    high_max = df['High'].rolling(k_period).max()
    k = 100 * (df['Close'] - low_min) / (high_max - low_min).replace(0, float('nan'))
    d = k.rolling(d_period).mean()
    return k, d


def calc_mfi(df, period=14):
    """MFI 자금흐름지수 (RSI + 거래량, >80=과매수, <20=과매도)"""
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    mf = tp * df['Volume']
    delta = tp.diff()
    pos_mf = mf.where(delta > 0, 0).rolling(period).sum()
    neg_mf = mf.where(delta < 0, 0).rolling(period).sum().abs()
    mfr = pos_mf / neg_mf.replace(0, float('nan'))
    return 100 - (100 / (1 + mfr))


def calc_obv_slope(df, period=20):
    """OBV 누적 거래량의 최근 추세 (양수=매집, 음수=분산)"""
    obv = ((df['Close'].diff() > 0).astype(int) - (df['Close'].diff() < 0).astype(int)) * df['Volume']
    obv = obv.cumsum()
    if len(obv) < period: return 0
    recent = obv.iloc[-period:]
    norm = recent.mean() if recent.mean() != 0 else 1
    slope = (recent.iloc[-1] - recent.iloc[0]) / abs(norm) * 100
    return float(slope) if not pd.isna(slope) else 0


# ════════════════════════════════════════════════════════════════
# 국가별 투자 성향 프로파일 (전략 파라미터 + 시장 특성)
# ════════════════════════════════════════════════════════════════
COUNTRY_PROFILES = {
    "KR": {
        "name": "한국",
        "tendency": "반도체·외인 주도 고변동성 추세장. 원화 약세시 수출주 강세, 외국인 매수세가 단기 방향 결정.",
        "ma_periods": (20, 50, 120),       # 한국은 200일보다 120일이 더 의미있음
        "rsi_band": (30, 70),
        "rsi_extreme": (25, 75),
        "vol_regime_mult": 1.4,
        "momentum_windows": (21, 63, 126),
        "trend_strength_min": 20,
        "vol_drop_threshold": -6,
        "use_volume": True,
    },
    "US": {
        "name": "미국",
        "tendency": "장기 추세 추종이 가장 잘 통하는 시장. 기관 자금이 MA200 기준선 역할. VIX>25에서 변동성 급증.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (35, 70),
        "rsi_extreme": (30, 75),
        "vol_regime_mult": 1.5,
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 25,
        "vol_drop_threshold": -5,
        "use_volume": True,
    },
    "JP": {
        "name": "일본",
        "tendency": "엔화 약세 = 수출주 강세 (USD/JPY 상승시 닛케이 상승). BoJ 금리인상 전환(2024~)으로 엔화 강세 시 수출주 압박 주의. 외국인 자금 유입 지속.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (30, 75),               # 일본 강세장에서 RSI 75 자주 돌파
        "rsi_extreme": (25, 80),
        "vol_regime_mult": 1.5,
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 20,
        "vol_drop_threshold": -5,
        "use_volume": False,
    },
    "CN": {
        "name": "중국",
        "tendency": "정책 주도 평균회귀형. 추세 지속력 약하고 RSI 극단(<25,>75)에서 반전 자주 발생. 정부 부양책 발표가 단기 반등 트리거.",
        "ma_periods": (10, 30, 100),       # 중국은 짧은 사이클
        "rsi_band": (30, 70),
        "rsi_extreme": (25, 75),            # 더 극단적 RSI 신호
        "vol_regime_mult": 1.5,
        "momentum_windows": (10, 30, 90),  # 짧은 momentum
        "trend_strength_min": 25,
        "vol_drop_threshold": -7,
        "use_volume": True,
    },
    "HK": {
        "name": "홍콩",
        "tendency": "본토 대비 외국인 접근 용이. 중국 정책 + 글로벌 자금흐름 이중 영향. 텐센트·알리바바 등 빅테크 비중↑.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (30, 70),
        "rsi_extreme": (25, 75),
        "vol_regime_mult": 1.6,
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 20,
        "vol_drop_threshold": -7,
        "use_volume": True,
    },
    "IN": {
        "name": "인도",
        "tendency": "강한 장기 성장 추세. 내수자금(국내 SIP)이 외인 매도를 상쇄. 추세 지속력 높으나 고점 대비 낙폭 클 때 추세 이탈 주의.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (35, 75),               # 강세장 RSI 70+ 흔함
        "rsi_extreme": (30, 80),
        "vol_regime_mult": 1.5,
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 20,
        "vol_drop_threshold": -5,
        "use_volume": True,
    },
    "TW": {
        "name": "대만",
        "tendency": "TSMC가 시총 30% 차지하는 반도체 프록시. AI/반도체 사이클 = 가권지수 사이클. 미국 SOX 지수와 강한 연동.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (30, 70),
        "rsi_extreme": (25, 75),
        "vol_regime_mult": 1.5,
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 20,
        "vol_drop_threshold": -6,
        "use_volume": True,
    },
    "EU": {
        "name": "유럽",
        "tendency": "낮은 변동성·고배당 시장. ECB 금리정책에 민감, 에너지·금융 비중 큼. 미국 대비 베타 0.7 수준.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (35, 70),
        "rsi_extreme": (30, 75),
        "vol_regime_mult": 1.3,             # 유럽은 변동성 임계값 낮춤
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 20,
        "vol_drop_threshold": -4,
        "use_volume": False,
    },
    "AU": {
        "name": "호주·뉴질랜드",
        "tendency": "원자재(철광석·석탄·금) 비중↑, 중국 수요와 강한 상관. 호주달러는 리스크온 통화.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (30, 70),
        "rsi_extreme": (25, 75),
        "vol_regime_mult": 1.5,
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 20,
        "vol_drop_threshold": -5,
        "use_volume": True,
    },
    "EM": {
        "name": "신흥국",
        "tendency": "USD 강세시 약세, 원자재 가격 민감. Fed 금리·달러지수(DXY) 방향이 핵심 변수.",
        "ma_periods": (15, 50, 200),
        "rsi_band": (25, 70),
        "rsi_extreme": (20, 75),
        "vol_regime_mult": 1.6,
        "momentum_windows": (21, 63, 126),
        "trend_strength_min": 20,
        "vol_drop_threshold": -8,
        "use_volume": True,
    },
    "ME": {
        "name": "중동",
        "tendency": "유가 변동에 직접 노출, 지정학 리스크↑. 사우디는 OPEC+ 정책, 이스라엘은 테크/방산 비중↑.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (30, 70),
        "rsi_extreme": (25, 75),
        "vol_regime_mult": 1.5,
        "momentum_windows": (21, 63, 210),
        "trend_strength_min": 20,
        "vol_drop_threshold": -6,
        "use_volume": False,
    },
    "CRYPTO": {
        "name": "크립토",
        "tendency": "24시간 거래·고변동성·4년 반감기 사이클. 비트코인 도미넌스가 알트코인 흐름 결정.",
        "ma_periods": (20, 50, 200),
        "rsi_band": (30, 75),
        "rsi_extreme": (25, 80),
        "vol_regime_mult": 1.5,
        "momentum_windows": (7, 30, 90),
        "trend_strength_min": 25,
        "vol_drop_threshold": -10,
        "use_volume": False,
    },
}

TICKER_COUNTRY = {
    "^KS11": "KR", "^KQ11": "KR",
    "^GSPC": "US", "^IXIC": "US", "^DJI": "US",
    "^N225": "JP",
    "^HSI": "HK",
    "000001.SS": "CN", "399001.SZ": "CN",
    "^NSEI": "IN", "^BSESN": "IN",
    "^TWII": "TW",
    "^GDAXI": "EU", "^FCHI": "EU", "^FTSE": "EU", "^STOXX50E": "EU", "^SSMI": "EU",
    "^IBEX": "EU", "FTSEMIB.MI": "EU", "^AEX": "EU", "^OMXSPI": "EU", "^OSEBX": "EU", "^ATX": "EU",
    "^AXJO": "AU", "^NZ50": "AU",
    "^BVSP": "EM", "^JKSE": "EM", "^KLSE": "EM", "^MXX": "EM", "^STI": "EM",
    "^WIG20": "EM", "XU100.IS": "EM", "^SET.BK": "EM", "PSEi.PS": "EM", "^MERV": "EM",
    "^J203.JO": "EM",
    "^TA125.TA": "ME", "^TASI.SR": "ME",
    "BTC-USD": "CRYPTO", "ETH-USD": "CRYPTO",
    "SOL-USD": "CRYPTO", "XRP-USD": "CRYPTO", "BNB-USD": "CRYPTO",
    "DOGE-USD": "CRYPTO", "ADA-USD": "CRYPTO", "AVAX-USD": "CRYPTO",
}

# ════════════════════════════════════════════════════════════════
# 추천 ETF 가이드 (ticker → 전략별 상품)
# ════════════════════════════════════════════════════════════════
MARKET_ETF = {
    # ── 한국 ──
    "^KS11": {
        "2x":  "KODEX 레버리지 (122630) · TIGER 200레버리지 (243890)",
        "1x":  "KODEX 200 (069500) · TIGER 200 (102110)",
        "inv": "KODEX 인버스 (114800) · KODEX 200선물인버스2X (252670)",
    },
    "^KQ11": {
        "2x":  "KODEX 코스닥150레버리지 (233740)",
        "1x":  "KODEX 코스닥150 (229200) · TIGER 코스닥150 (232080)",
        "inv": "KODEX 코스닥150인버스(H) (251340)",
    },
    # ── 미국 ──
    "^GSPC": {
        "2x":  "KODEX 미국S&P500레버리지(H) (214980) · SSO",
        "1x":  "TIGER 미국S&P500 (360750) · SPY · VOO",
        "inv": "KODEX 미국S&P500선물인버스(H) (219480) · SH",
    },
    "^IXIC": {
        "2x":  "TIGER 미국나스닥100레버리지(H) (433580) · QLD",
        "1x":  "TIGER 미국나스닥100 (133690) · QQQ",
        "inv": "KODEX 미국나스닥100선물인버스(H) (314250) · PSQ",
    },
    "^DJI": {
        "2x":  "DDM (ProShares Ultra Dow30)",
        "1x":  "DIA (SPDR Dow Jones ETF)",
        "inv": "DOG (ProShares Short Dow30) · SDOW(3x)",
    },
    # ── 일본 (레버리지 전환) ──
    "^N225": {
        "2x":  "1570.T (NEXT FUNDS Nikkei 2x) · EZJ",
        "1x":  "TIGER 일본니케이225 (241180) · EWJ",
        "inv": "1357.T (일본인버스 2x) · 현금",
    },
    # ── 홍콩 (레버리지 전환) ──
    "^HSI": {
        "2x":  "YINN (Direxion China Bull 3x) · XPP",
        "1x":  "TIGER 차이나항셍테크 (371460) · EWH",
        "inv": "YANG (Direxion China Bear 3x) · 현금",
    },
    # ── 유럽 DAX (레버리지 전환) ──
    "^GDAXI": {
        "2x":  "LDAX (Lyxor DAX 2x) · DBX0BV (DAX 2x 유럽 상장)",
        "1x":  "EWG (iShares Germany) · DAXEX",
        "inv": "SDAX 인버스 ETF · 현금",
    },
    "^FCHI": {
        "1x":   "EWQ (iShares France) · VGK",
        "exit": "현금 보유",
    },
    "^FTSE": {
        "1x":   "EWU (iShares UK)",
        "exit": "현금 보유",
    },
    "^STOXX50E": {
        "2x":  "UPV (ProShares Ultra FTSE Europe)",
        "1x":  "TIGER 유럽STOXX50(H) (195930) · VGK · EZU",
        "inv": "EPV (ProShares UltraShort) · 현금",
    },
    "^SSMI": {
        "1x":   "EWL (iShares Switzerland)",
        "exit": "현금 보유",
    },
    "^IBEX": {
        "1x":   "EWP (iShares Spain) · VGK",
        "exit": "현금 보유",
    },
    "FTSEMIB.MI": {
        "1x":   "EWI (iShares Italy) · VGK",
        "exit": "현금 보유",
    },
    "^AEX": {
        "1x":   "EWN (iShares Netherlands) · VGK",
        "exit": "현금 보유",
    },
    "^OMXSPI": {
        "1x":   "EWD (iShares Sweden) · VGK",
        "exit": "현금 보유",
    },
    "^OSEBX": {
        "1x":   "NORW (Global X Norway)",
        "exit": "현금 보유",
    },
    "^ATX": {
        "1x":   "EWO (iShares Austria) · VGK",
        "exit": "현금 보유",
    },
    # ── 중국 (레버리지 전환) ──
    "000001.SS": {
        "2x":  "CHAU (Direxion CSI300 Bull 2x) · YINN(3x)",
        "1x":  "TIGER 차이나CSI300 (192090) · FXI · MCHI",
        "inv": "YANG (Direxion China Bear 3x) · 현금",
    },
    "399001.SZ": {
        "2x":  "YINN (Direxion China Bull 3x) · CHAU",
        "1x":  "MCHI (iShares China) · KWEB",
        "inv": "YANG (Direxion China Bear 3x) · 현금",
    },
    # ── 인도 ──
    "^NSEI": {
        "2x":  "INDL (Direxion India Bull 2x)",
        "1x":  "TIGER 인도니프티50 (437080) · INDA · EPI",
        "inv": "현금 보유",
    },
    "^BSESN": {
        "2x":  "INDL (Direxion India Bull 2x)",
        "1x":  "TIGER 인도니프티50 (437080) · EPI",
        "inv": "현금 보유",
    },
    # ── 대만 ──
    "^TWII": {
        "2x":  "현지 00631L (Yuanta 2x) · FTXS",
        "1x":  "EWT (iShares Taiwan) · CQQQ",
        "inv": "현금 보유",
    },
    # ── 호주 (레버리지 전환) ──
    "^AXJO": {
        "2x":  "GEAR (BetaShares Aus Equities 2x)",
        "1x":  "EWA (iShares Australia) · IAF",
        "inv": "BBOZ (BetaShares Aus Bear 2x) · 현금",
    },
    "^NZ50": {
        "1x":   "ENZL (iShares New Zealand)",
        "exit": "현금 보유",
    },
    # ── 신흥국 (브라질 레버리지 전환) ──
    "^BVSP": {
        "2x":  "BRZU (Direxion Brazil Bull 3x)",
        "1x":  "EWZ (iShares Brazil)",
        "inv": "BRZS (Direxion Brazil Bear 3x) · 현금",
    },
    "^JKSE": {
        "1x":   "EIDO (iShares Indonesia)",
        "exit": "현금 보유",
    },
    "^KLSE": {
        "1x":   "EWM (iShares Malaysia)",
        "exit": "현금 보유",
    },
    "^MXX": {
        "1x":   "EWW (iShares Mexico)",
        "exit": "현금 보유",
    },
    "^STI": {
        "1x":   "EWS (iShares Singapore)",
        "exit": "현금 보유",
    },
    "^WIG20": {
        "1x":   "EPOL (iShares Poland)",
        "exit": "현금 보유",
    },
    "XU100.IS": {
        "1x":   "TUR (iShares Turkey)",
        "exit": "현금 보유",
    },
    "^J203.JO": {
        "1x":   "EZA (iShares South Africa)",
        "exit": "현금 보유",
    },
    "^SET.BK": {
        "1x":   "THD (iShares Thailand)",
        "exit": "현금 보유",
    },
    "PSEi.PS": {
        "1x":   "EPHE (iShares Philippines)",
        "exit": "현금 보유",
    },
    "^MERV": {
        "1x":   "ARGT (Global X Argentina)",
        "exit": "현금 보유",
    },
    # ── 중동 ──
    "^TA125.TA": {
        "1x":   "EIS (iShares Israel)",
        "exit": "현금 보유",
    },
    "^TASI.SR": {
        "1x":   "KSA (iShares Saudi Arabia)",
        "exit": "현금 보유",
    },
    # ── 크립토 ──
    "BTC-USD": {
        "2x":  "BITX (ProShares Ultra Bitcoin 2x) · MSTU",
        "1x":  "IBIT (BlackRock BTC Spot) · FBTC · 현물 직접 보유",
        "inv": "SBIT (ProShares Short Bitcoin) · USDT 전환",
    },
    "ETH-USD": {
        "1x":   "ETHA (iShares ETH Spot) · ETHW · 현물 직접 보유",
        "exit": "USDT 스테이블코인 전환",
    },
    "SOL-USD": {
        "1x":   "SOLS (Bitwise Solana) · BSOL · 현물 직접 보유",
        "exit": "USDT 스테이블코인 전환",
    },
    "XRP-USD": {
        "1x":   "XRPH (ProShares XRP) · 현물 직접 보유",
        "exit": "USDT 스테이블코인 전환",
    },
    "BNB-USD": {
        "1x":   "현물 직접 보유 (바이낸스)",
        "exit": "USDT 스테이블코인 전환",
    },
    "DOGE-USD": {
        "1x":   "현물 직접 보유 (업비트·바이낸스)",
        "exit": "USDT 스테이블코인 전환",
    },
    "ADA-USD": {
        "1x":   "현물 직접 보유",
        "exit": "USDT 스테이블코인 전환",
    },
    "AVAX-USD": {
        "1x":   "현물 직접 보유",
        "exit": "USDT 스테이블코인 전환",
    },
}


def get_country_profile(ticker):
    code = TICKER_COUNTRY.get(ticker, "US")
    return code, COUNTRY_PROFILES[code]


# ════════════════════════════════════════════════════════════════
# 데이터 로드
# ════════════════════════════════════════════════════════════════
def load_data(ticker, period="2y"):
    try:
        df = yf.download(ticker, period=period, auto_adjust=True,
                         progress=False, threads=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"  ⚠️ {ticker}: {e}")
        return pd.DataFrame()


# ════════════════════════════════════════════════════════════════
# 전략 1: 미너비니 추세추종 (크립토용)
# ════════════════════════════════════════════════════════════════
def analyze_minervini(df, params):
    p = params
    close = df['Close']; high = df['High']; low = df['Low']
    ma_f = close.rolling(p['ma_fast']).mean()
    ma_s = close.rolling(p['ma_slow']).mean()
    rsi = calc_rsi(close)
    atr = calc_atr(df)

    i = len(df) - 1
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    _mf = float(ma_f.iloc[-1]) if not pd.isna(ma_f.iloc[-1]) else current
    _ms = float(ma_s.iloc[-1]) if not pd.isna(ma_s.iloc[-1]) else current
    _rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    _atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else current * 0.03

    slope = 0
    if i >= 5 and not pd.isna(ma_s.iloc[i-5]):
        slope = (float(ma_s.iloc[i]) - float(ma_s.iloc[i-5])) / float(ma_s.iloc[i-5]) * 100

    is_stage2 = current > _mf > _ms and slope > 0 and _rsi >= p['entry_rsi']

    # 동적 목표/손절
    trailing_stop = current - _atr * p['trailing_atr']
    ma_exit = _ms - _atr * p['exit_buffer_atr']
    hard_stop = current * (1 - p['hard_stop_pct'])
    stoploss = max(trailing_stop, ma_exit, hard_stop)

    # ATR 배수 기반 목표: stage2=3x, 일반=2x ATR
    atr_mult = 3.0 if is_stage2 else 2.0
    target_atr = current + _atr * atr_mult

    risk = current - stoploss
    reward = target_atr - current
    rr = reward / risk if risk > 0 else 0

    # R:R이 2.0 미만이면 목표를 ATR 배수로 늘리되, 최대 5x ATR까지만 허용
    if rr < 2.0 and risk > 0:
        target_atr = current + risk * 2.0
        # 단, ATR×5 상한으로 비현실적인 목표 방지
        target_atr = min(target_atr, current + _atr * 5.0)
        rr = (target_atr - current) / risk

    target = target_atr

    if is_stage2:
        signal = "🟢 매수 (Stage2)"
        signal_type = "BUY"
    elif current < _ms:
        signal = "🔴 매도 (MA이탈)"
        signal_type = "SELL"
    else:
        signal = "⚪ 관망"
        signal_type = "NEUTRAL"

    return {
        "signal": signal, "signal_type": signal_type,
        "is_stage2": is_stage2,
        "price": current, "change_pct": (current-prev)/prev*100,
        "ma_fast": _mf, "ma_slow": _ms, "ma_slope": slope,
        "rsi": _rsi, "atr": _atr, "atr_pct": _atr/current*100,
        "target": round(target, 2), "target_pct": round((target-current)/current*100, 2),
        "stoploss": round(stoploss, 2), "stop_pct": round((current-stoploss)/current*100, 2),
        "rr_ratio": round(rr, 2),
        "strategy_name": "미너비니 추세추종",
        "strategy_label": f"MA{p['ma_fast']}/{p['ma_slow']} Trail×{p['trailing_atr']}",
    }


# ════════════════════════════════════════════════════════════════
# 전략 2: 레버리지 스위칭 (한국/미국 지수용)
# ════════════════════════════════════════════════════════════════
def analyze_leverage(df, params, profile=None):
    """레버리지 스위칭: MA50/200 + ADX 추세강도 + 변동성 필터.
    국가 프로파일이 있으면 MA 기간·RSI 임계·변동성 임계값 조정."""
    p = profile or COUNTRY_PROFILES["US"]
    ma_s, ma_m, ma_l = p["ma_periods"]
    rsi_lo, rsi_hi = p["rsi_band"]
    vol_mult = p["vol_regime_mult"]
    adx_min = p["trend_strength_min"]

    close = df['Close']
    ma_mid  = close.rolling(ma_m).mean()
    ma_long = close.rolling(ma_l).mean()
    rsi  = calc_rsi(close)
    adx, plus_di, minus_di = calc_adx(df, period=14)
    stoch_k, stoch_d = calc_stochastic(df, k_period=14, d_period=3)
    vol20 = close.pct_change().rolling(20).std()
    vol60 = close.pct_change().rolling(60).std()

    i = len(df) - 1
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    _ma_m = float(ma_mid.iloc[-1])  if not pd.isna(ma_mid.iloc[-1])  else current
    _ma_l = float(ma_long.iloc[-1]) if not pd.isna(ma_long.iloc[-1]) else current
    _rsi  = float(rsi.iloc[-1])     if not pd.isna(rsi.iloc[-1])     else 50
    _adx  = float(adx.iloc[-1])     if not pd.isna(adx.iloc[-1])     else 15
    _pdi  = float(plus_di.iloc[-1]) if not pd.isna(plus_di.iloc[-1]) else 0
    _mdi  = float(minus_di.iloc[-1])if not pd.isna(minus_di.iloc[-1])else 0
    _stk  = float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50
    _v20  = float(vol20.iloc[-1])   if not pd.isna(vol20.iloc[-1])   else 0.01
    _v60  = float(vol60.iloc[-1])   if not pd.isna(vol60.iloc[-1])   else 0.01

    slope_mid = 0
    if i >= 5 and not pd.isna(ma_mid.iloc[i-5]):
        slope_mid = (float(ma_mid.iloc[i]) - float(ma_mid.iloc[i-5])) / float(ma_mid.iloc[i-5]) * 100

    vol_spike = _v20 > _v60 * vol_mult if _v60 > 0 else False
    trend_strong = _adx >= adx_min
    trend_up     = _pdi > _mdi

    # 골든/데드크로스 감지
    cross_signal = "none"
    if i >= 1 and not pd.isna(ma_mid.iloc[-2]) and not pd.isna(ma_long.iloc[-2]):
        prev_m = float(ma_mid.iloc[-2]);  prev_l = float(ma_long.iloc[-2])
        if prev_m < prev_l and _ma_m >= _ma_l:   cross_signal = "golden"
        elif prev_m > prev_l and _ma_m <= _ma_l: cross_signal = "dead"
        elif _ma_m > _ma_l:                       cross_signal = "bull"
        else:                                     cross_signal = "bear"

    # ── 신뢰도 (confidence) 산출 0-100 ──
    confidence = 50
    if current > _ma_m: confidence += 10
    if current > _ma_l: confidence += 10
    if slope_mid > 0:   confidence += 10
    if trend_strong:    confidence += 10
    if trend_up:        confidence += 5
    if rsi_lo < _rsi < rsi_hi: confidence += 5
    if vol_spike: confidence -= 15
    if cross_signal == "golden": confidence += 10
    if cross_signal == "dead":   confidence -= 15
    confidence = max(0, min(100, confidence))

    # ── 레버리지 결정 (점수제: 6개 조건 → 2x/1x/0x) ──
    # 6개 조건에 가중치를 부여하여 AND 경직성 해소
    score_2x = 0
    if current > _ma_m > _ma_l: score_2x += 2  # 핵심 추세 정렬 (가중치 2)
    if slope_mid > 0:            score_2x += 1  # MA중기 상승기울기
    if _rsi > 50:                score_2x += 1  # RSI 중립 이상
    if trend_strong:             score_2x += 1  # ADX 추세강도 확인
    if trend_up:                 score_2x += 1  # +DI > -DI (방향 확인)
    # 최대 점수: 6점

    if current < _ma_l:
        # 장기 MA 하단 = 무조건 현금 (하락장)
        lev = 0.0
        signal = "🔴 현금 전환 (장기추세 이탈)"
        signal_type = "CASH"
    elif vol_spike and current < _ma_m:
        # 변동성 급등 + 중기선 하단 = 현금
        lev = 0.0
        signal = "🔴 현금 (변동성 급등)"
        signal_type = "CASH_VOL"
    elif score_2x >= 5 and not vol_spike:
        # 5~6점: 2x 레버리지 (강한 상승추세)
        lev = 2.0
        signal = "🟢 2x 레버리지 (강한 상승추세)"
        signal_type = "LEVERAGE_2X"
    elif score_2x >= 3 or (current > _ma_l and not vol_spike):
        # 3~4점 or 장기선 위: 1x 보유
        lev = 1.0
        signal = "🔵 1x 원물 보유"
        signal_type = "HOLD_1X"
    else:
        lev = 1.0
        signal = "⚪ 1x 원물"
        signal_type = "HOLD_1X"

    # ── 횡보 변동성 보호: 레버리지 ETF 베타슬리피지 방지 ──
    # 연환산 변동성 25% 초과 + ADX 추세 미확정 → 2x 강제 다운그레이드
    ann_vol = _v20 * np.sqrt(252) * 100
    if lev == 2.0 and ann_vol > 25 and not trend_strong:
        lev = 1.0
        signal = "🔵 1x 다운그레이드 (횡보 변동성 과다)"
        signal_type = "HOLD_1X"

    return {
        "signal": signal, "signal_type": signal_type,
        "leverage": lev,
        "price": current, "change_pct": (current-prev)/prev*100,
        "ma50": _ma_m, "ma200": _ma_l, "ma50_slope": slope_mid,
        "rsi": _rsi, "adx": round(_adx, 1),
        "trend_strong": trend_strong, "trend_up": trend_up,
        "stoch_k": round(_stk, 1),
        "vol_spike": vol_spike,
        "ann_vol": round(ann_vol, 1),
        "cross_signal": cross_signal,
        "confidence": confidence,
        "score_2x": score_2x,
        "strategy_name": "레버리지 스위칭 v2",
        "strategy_label": f"2x/1x/0x · MA{ma_m}/{ma_l} · ADX{_adx:.0f}",
    }


# ════════════════════════════════════════════════════════════════
# 전략 3: 이중필터 모멘텀 (NIKKEI/항셍용)
# ════════════════════════════════════════════════════════════════
def analyze_dual_filter(df, params, profile=None):
    """이중필터 모멘텀: 단·중·장기 3개 모멘텀 + ADX 추세강도 + Stochastic 극단.
    국가별 모멘텀 윈도우 차등 적용 (중국=10/30/90, 미국=21/63/210)."""
    p = profile or COUNTRY_PROFILES["JP"]
    w_short, w_mid, w_long = p["momentum_windows"]
    rsi_lo, rsi_hi = p["rsi_band"]
    rsi_x_lo, rsi_x_hi = p["rsi_extreme"]
    adx_min = p["trend_strength_min"]

    close = df['Close']
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current

    n = len(close)
    mom_s = (current / float(close.iloc[-w_short]) - 1) * 100 if n >= w_short else 0
    mom_m = (current / float(close.iloc[-w_mid])   - 1) * 100 if n >= w_mid   else 0
    mom_l = (current / float(close.iloc[-w_long])  - 1) * 100 if n >= w_long  else 0

    rsi_val = float(calc_rsi(close).iloc[-1]) if not pd.isna(calc_rsi(close).iloc[-1]) else 50
    adx, plus_di, minus_di = calc_adx(df, period=14)
    _adx = float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 15
    _pdi = float(plus_di.iloc[-1]) if not pd.isna(plus_di.iloc[-1]) else 0
    _mdi = float(minus_di.iloc[-1]) if not pd.isna(minus_di.iloc[-1]) else 0
    stoch_k, stoch_d = calc_stochastic(df, k_period=14, d_period=3)
    _stk = float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50

    pos_count = sum(1 for m in (mom_s, mom_m, mom_l) if m > 0)
    neg_count = 3 - pos_count
    trend_strong = _adx >= adx_min
    trend_up = _pdi > _mdi

    # 극단 RSI = 평균회귀 신호 (중국형 시장에서 유용)
    rsi_extreme_low  = rsi_val <= rsi_x_lo
    rsi_extreme_high = rsi_val >= rsi_x_hi

    if pos_count == 3 and trend_strong and trend_up:
        signal = "🟢 강력 매수 (3모멘텀+추세확정)"
        signal_type = "STRONG_BUY"
        action = "강력 매수"
        confidence = 85
    elif pos_count == 3 and (trend_strong or trend_up):
        # 3모멘텀 but ADX or 방향 하나만 확정 → 일반 매수
        signal = "🟢 매수 (3모멘텀·추세 부분확정)"
        signal_type = "BUY"
        action = "매수"
        confidence = 72
    elif pos_count == 2 and trend_strong and trend_up:
        # 2모멘텀 + 추세 확정 → 투자 유지
        signal = "🟢 투자 유지 (2모멘텀+추세확정)"
        signal_type = "INVESTED"
        action = "투자 유지"
        confidence = 65
    elif pos_count == 2:
        # 2모멘텀 but 추세 미확정 → 소극적 관망
        signal = "⚪ 관망 (2모멘텀·추세 미확정)"
        signal_type = "NEUTRAL"
        action = "관망"
        confidence = 48
    elif rsi_extreme_low and pos_count == 0:
        signal = "🟡 반등 대기 (과매도 극단)"
        signal_type = "CAUTION"
        action = "분할 매수 검토"
        confidence = 55
    elif neg_count == 3 and trend_strong and not trend_up:
        # 전구간 음모멘텀 + 하락추세 확인 → 강한 현금
        signal = "🔴 현금 (전 구간 음모멘텀+하락추세)"
        signal_type = "CASH"
        action = "현금 전환"
        confidence = 80
    elif neg_count == 3:
        signal = "🔴 현금 (전 구간 음모멘텀)"
        signal_type = "CASH"
        action = "현금 전환"
        confidence = 70
    elif rsi_extreme_high and trend_strong and not trend_up:
        signal = "🔴 매도 (과열+하락추세)"
        signal_type = "SELL"
        action = "분할 매도"
        confidence = 70
    else:
        signal = "⚪ 관망"
        signal_type = "NEUTRAL"
        action = "관망"
        confidence = 40

    return {
        "signal": signal, "signal_type": signal_type,
        "price": current, "change_pct": (current-prev)/prev*100,
        "mom_short": round(mom_s, 2), "mom_mid": round(mom_m, 2), "mom_long": round(mom_l, 2),
        "mom_3m": round(mom_m, 2), "mom_10m": round(mom_l, 2),  # 호환성
        "mom_windows": [w_short, w_mid, w_long],
        "rsi": rsi_val, "adx": round(_adx, 1),
        "trend_strong": trend_strong, "trend_up": trend_up,
        "stoch_k": round(_stk, 1),
        "action": action,
        "confidence": confidence,
        "strategy_name": "이중필터 모멘텀 v2",
        "strategy_label": f"{w_short}/{w_mid}/{w_long}일 · ADX{_adx:.0f}",
    }


# ════════════════════════════════════════════════════════════════
# 전략 4: 위기방어형 (DAX + BTC 현물용)
# ════════════════════════════════════════════════════════════════
def analyze_risk_defense(df, params, profile=None):
    """위기방어형: 8개 위험요인 가중치 점수화. 국가별 변동성·하락 임계값 차등.
    추가 지표: ADX(추세 약화), MFI(자금이탈), Bollinger %B."""
    p = profile or COUNTRY_PROFILES["US"]
    ma_s, ma_m, ma_l = p["ma_periods"]
    vol_mult = p["vol_regime_mult"]
    drop_threshold = p["vol_drop_threshold"]

    close = df['Close']
    ma_mid  = close.rolling(ma_m).mean()
    ma_long = close.rolling(ma_l).mean()
    rsi = calc_rsi(close)
    adx, plus_di, minus_di = calc_adx(df, period=14)
    ann_factor = np.sqrt(365) if params.get('is_crypto') else np.sqrt(252)
    vol20 = close.pct_change().rolling(20).std() * ann_factor * 100
    vol60 = close.pct_change().rolling(60).std() * ann_factor * 100

    i = len(df) - 1
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    _ma_m = float(ma_mid.iloc[-1])  if not pd.isna(ma_mid.iloc[-1])  else current
    _ma_l = float(ma_long.iloc[-1]) if not pd.isna(ma_long.iloc[-1]) else current
    _rsi  = float(rsi.iloc[-1])     if not pd.isna(rsi.iloc[-1])     else 50
    _adx  = float(adx.iloc[-1])     if not pd.isna(adx.iloc[-1])     else 15
    _pdi  = float(plus_di.iloc[-1]) if not pd.isna(plus_di.iloc[-1]) else 0
    _mdi  = float(minus_di.iloc[-1])if not pd.isna(minus_di.iloc[-1])else 0
    _v20  = float(vol20.iloc[-1])   if not pd.isna(vol20.iloc[-1])   else 20
    _v60  = float(vol60.iloc[-1])   if not pd.isna(vol60.iloc[-1])   else 20
    r20 = (current / float(close.iloc[i-20]) - 1) * 100 if i >= 20 else 0

    # MFI 자금흐름
    try:
        mfi = calc_mfi(df, period=14)
        _mfi = float(mfi.iloc[-1]) if not pd.isna(mfi.iloc[-1]) else 50
    except Exception:
        _mfi = 50

    # Bollinger %B
    try:
        _, _, _, bb_pct_b, _ = calc_bollinger(close)
    except Exception:
        bb_pct_b = 0.5

    risk_score = 0
    risk_details = []
    if current < _ma_l:           risk_score += 25; risk_details.append("MA장기↓")
    if current < _ma_m:           risk_score += 12; risk_details.append("MA중기↓")
    if _ma_m < _ma_l:             risk_score += 12; risk_details.append("데드크로스")
    if _rsi < 40:                 risk_score += 8;  risk_details.append(f"RSI{_rsi:.0f}")
    if r20 < drop_threshold:      risk_score += 12; risk_details.append(f"20일{r20:.1f}%")
    if _v20 > _v60 * vol_mult:    risk_score += 12; risk_details.append("변동성↑")
    if _adx > 25 and _mdi > _pdi: risk_score += 10; risk_details.append("하락추세강함")
    if _mfi < 30:                 risk_score += 5;  risk_details.append(f"MFI{_mfi:.0f}(자금이탈)")
    if bb_pct_b < 0.1:            risk_score += 4;  risk_details.append("BB하단이탈")

    risk_score = min(100, risk_score)

    if risk_score >= 70:
        signal = f"🔴 현금 전환 (위험 {risk_score}점)"
        signal_type = "CASH"
    elif risk_score >= 50:
        signal = f"🟡 주의 (위험 {risk_score}점)"
        signal_type = "CAUTION"
    elif risk_score <= 25:
        signal = f"🟢 투자 유지 (위험 {risk_score}점)"
        signal_type = "INVESTED"
    else:
        signal = f"⚪ 관망 (위험 {risk_score}점)"
        signal_type = "NEUTRAL"

    confidence = 100 - risk_score if signal_type == "INVESTED" else risk_score

    return {
        "signal": signal, "signal_type": signal_type,
        "risk_score": risk_score, "risk_details": risk_details,
        "price": current, "change_pct": (current-prev)/prev*100,
        "rsi": _rsi, "adx": round(_adx, 1),
        "mfi": round(_mfi, 1),
        "ma50": _ma_m, "ma200": _ma_l,
        "vol20": round(_v20, 1), "vol60": round(_v60, 1),
        "r20": round(r20, 2),
        "confidence": confidence,
        "strategy_name": "위기방어형 v2",
        "strategy_label": f"위험 {risk_score}/100 · MA{ma_m}/{ma_l}",
    }


# ════════════════════════════════════════════════════════════════
# 통합 분석 라우터
# ════════════════════════════════════════════════════════════════
def analyze_market(ticker, market_info, df):
    strategy = market_info["strategy"]
    params = market_info["params"]
    country_code, profile = get_country_profile(ticker)

    if strategy == "minervini":
        result = analyze_minervini(df, params)
    elif strategy == "leverage":
        result = analyze_leverage(df, params, profile=profile)
    elif strategy == "dual_filter":
        result = analyze_dual_filter(df, params, profile=profile)
    elif strategy == "risk_defense":
        result = analyze_risk_defense(df, params, profile=profile)
    else:
        return None

    # 추가 보조 지표 (모든 전략 공통)
    try:
        obv_slope = calc_obv_slope(df, period=20)
    except Exception:
        obv_slope = 0

    # 공통 필드 추가
    close = df['Close']
    result.update({
        "ticker": ticker,
        "name": market_info["name"],
        "symbol": market_info["symbol"],
        "flag": market_info["flag"],
        "strategy": strategy,
        "country_code": country_code,
        "country_name": profile["name"],
        "country_tendency": profile["tendency"],
        "obv_slope": round(obv_slope, 2),
        "high_1y": float(df['High'].max()),
        "low_1y": float(df['Low'].min()),
        "from_high_pct": round((result['price'] - float(df['High'].max())) / float(df['High'].max()) * 100, 1),
        "price_history": _build_price_history(df, n=20),
        "etf": MARKET_ETF.get(ticker, {}),
    })
    return result


# ════════════════════════════════════════════════════════════════
# 백테스트 엔진
# ════════════════════════════════════════════════════════════════

def _bt_positions_leverage(df, params, profile):
    """레버리지 전략 - 포지션 배열 생성 (0/1/2)"""
    ma_s, ma_m, ma_l = profile["ma_periods"]
    vol_mult = profile["vol_regime_mult"]
    adx_min = profile["trend_strength_min"]

    close = df['Close']
    n = len(close)
    ma_mid  = close.rolling(ma_m).mean()
    ma_long = close.rolling(ma_l).mean()
    rsi_s   = calc_rsi(close)
    adx_s, pdi_s, mdi_s = calc_adx(df, period=14)
    v20_s = close.pct_change().rolling(20).std()
    v60_s = close.pct_change().rolling(60).std()
    slope_s = (ma_mid - ma_mid.shift(5)) / ma_mid.shift(5).replace(0, np.nan) * 100

    positions = np.zeros(n)
    start = max(ma_l + 10, 60)
    for i in range(start, n):
        c   = float(close.iloc[i])
        mm  = float(ma_mid.iloc[i])  if not pd.isna(ma_mid.iloc[i])  else c
        ml  = float(ma_long.iloc[i]) if not pd.isna(ma_long.iloc[i]) else c
        rsi = float(rsi_s.iloc[i])   if not pd.isna(rsi_s.iloc[i])   else 50
        adx = float(adx_s.iloc[i])   if not pd.isna(adx_s.iloc[i])   else 15
        pdi = float(pdi_s.iloc[i])   if not pd.isna(pdi_s.iloc[i])   else 0
        mdi = float(mdi_s.iloc[i])   if not pd.isna(mdi_s.iloc[i])   else 0
        v20 = float(v20_s.iloc[i])   if not pd.isna(v20_s.iloc[i])   else 0.01
        v60 = float(v60_s.iloc[i])   if not pd.isna(v60_s.iloc[i])   else 0.01
        sl  = float(slope_s.iloc[i]) if not pd.isna(slope_s.iloc[i]) else 0

        vs = v20 > v60 * vol_mult if v60 > 0 else False
        ts = adx >= adx_min
        tu = pdi > mdi

        if c < ml or (vs and c < mm):
            positions[i] = 0.0
            continue

        score = 0
        if c > mm > ml: score += 2
        if sl > 0: score += 1
        if rsi > 50: score += 1
        if ts: score += 1
        if tu: score += 1

        if score >= 5 and not vs:
            pos = 2.0
            ann_vol = v20 * np.sqrt(252) * 100
            if ann_vol > 25 and not ts:
                pos = 1.0
        else:
            pos = 1.0
        positions[i] = pos
    return positions


def _bt_positions_dual(df, params, profile):
    """이중필터 전략 - 포지션 배열 생성 (0/0.5/1)"""
    w_short, w_mid, w_long = profile["momentum_windows"]
    adx_min = profile["trend_strength_min"]

    close = df['Close']
    n = len(close)
    adx_s, pdi_s, mdi_s = calc_adx(df, period=14)

    positions = np.zeros(n)
    start = max(w_long + 5, 30)
    for i in range(start, n):
        c = float(close.iloc[i])
        mom_s = (c / float(close.iloc[i - w_short]) - 1) if i >= w_short else 0
        mom_m = (c / float(close.iloc[i - w_mid])   - 1) if i >= w_mid   else 0
        mom_l = (c / float(close.iloc[i - w_long])  - 1) if i >= w_long  else 0
        adx = float(adx_s.iloc[i]) if not pd.isna(adx_s.iloc[i]) else 15
        pdi = float(pdi_s.iloc[i]) if not pd.isna(pdi_s.iloc[i]) else 0
        mdi = float(mdi_s.iloc[i]) if not pd.isna(mdi_s.iloc[i]) else 0
        pos_count = sum(1 for m in (mom_s, mom_m, mom_l) if m > 0)
        ts = adx >= adx_min
        tu = pdi > mdi
        if pos_count == 3 or (pos_count >= 2 and ts and tu):
            positions[i] = 1.0
        elif pos_count == 2:
            positions[i] = 0.5
    return positions


def _bt_positions_minervini(df, params):
    """미너비니 전략 - 포지션 배열 생성 (0/1)"""
    close = df['Close']
    n = len(close)
    ma_f  = close.rolling(params['ma_fast']).mean()
    ma_s  = close.rolling(params['ma_slow']).mean()
    rsi_s = calc_rsi(close)
    slope_s = (ma_s - ma_s.shift(5)) / ma_s.shift(5).replace(0, np.nan) * 100

    positions = np.zeros(n)
    start = max(params['ma_slow'] + 10, 30)
    for i in range(start, n):
        c   = float(close.iloc[i])
        mf  = float(ma_f.iloc[i])  if not pd.isna(ma_f.iloc[i])  else c
        ms  = float(ma_s.iloc[i])  if not pd.isna(ma_s.iloc[i])  else c
        rsi = float(rsi_s.iloc[i]) if not pd.isna(rsi_s.iloc[i]) else 50
        sl  = float(slope_s.iloc[i]) if not pd.isna(slope_s.iloc[i]) else 0
        if c > mf > ms and sl > 0 and rsi >= params['entry_rsi']:
            positions[i] = 1.0
    return positions


def _bt_positions_risk(df, params, profile):
    """위기방어형 전략 - 포지션 배열 생성 (0/1)"""
    ma_s, ma_m, ma_l = profile["ma_periods"]
    vol_mult = profile["vol_regime_mult"]
    drop_threshold = profile["vol_drop_threshold"]

    close = df['Close']
    n = len(close)
    ma_mid  = close.rolling(ma_m).mean()
    ma_long = close.rolling(ma_l).mean()
    rsi_s   = calc_rsi(close)
    adx_s, pdi_s, mdi_s = calc_adx(df, period=14)
    v20_s = close.pct_change().rolling(20).std() * np.sqrt(252) * 100
    v60_s = close.pct_change().rolling(60).std() * np.sqrt(252) * 100

    positions = np.zeros(n)
    start = max(ma_l + 10, 60)
    for i in range(start, n):
        c   = float(close.iloc[i])
        mm  = float(ma_mid.iloc[i])  if not pd.isna(ma_mid.iloc[i])  else c
        ml  = float(ma_long.iloc[i]) if not pd.isna(ma_long.iloc[i]) else c
        rsi = float(rsi_s.iloc[i])   if not pd.isna(rsi_s.iloc[i])   else 50
        adx = float(adx_s.iloc[i])   if not pd.isna(adx_s.iloc[i])   else 15
        pdi = float(pdi_s.iloc[i])   if not pd.isna(pdi_s.iloc[i])   else 0
        mdi = float(mdi_s.iloc[i])   if not pd.isna(mdi_s.iloc[i])   else 0
        v20 = float(v20_s.iloc[i])   if not pd.isna(v20_s.iloc[i])   else 20
        v60 = float(v60_s.iloc[i])   if not pd.isna(v60_s.iloc[i])   else 20
        r20 = (c / float(close.iloc[i - 20]) - 1) * 100 if i >= 20 else 0

        risk = 0
        if c < ml: risk += 25
        if c < mm: risk += 12
        if mm < ml: risk += 12
        if rsi < 40: risk += 8
        if r20 < drop_threshold: risk += 12
        if v20 > v60 * vol_mult: risk += 12
        if adx > 25 and mdi > pdi: risk += 10
        positions[i] = 0.0 if min(100, risk) >= 50 else 1.0
    return positions


def backtest_strategy(ticker, market_info, period="10y"):
    """10년 백테스트: CAGR, MDD, Sharpe, Buy&Hold 비교.
    레버리지 비용(2x=연0.5%, ETF보수=연0.1%) 반영."""
    import datetime as _dt

    df = load_data(ticker, period=period)
    if df is None or len(df) < 250:
        return None

    strategy = market_info["strategy"]
    params   = market_info["params"]
    _, profile = get_country_profile(ticker)

    close_arr = df['Close'].values.astype(float)
    n = len(close_arr)

    try:
        if strategy == "leverage":
            pos_arr = _bt_positions_leverage(df, params, profile)
        elif strategy == "dual_filter":
            pos_arr = _bt_positions_dual(df, params, profile)
        elif strategy == "minervini":
            pos_arr = _bt_positions_minervini(df, params)
        elif strategy == "risk_defense":
            pos_arr = _bt_positions_risk(df, params, profile)
        else:
            pos_arr = np.ones(n)
    except Exception as e:
        print(f"  ⚠️ backtest {ticker}: {e}")
        return None

    daily_ret = np.zeros(n)
    daily_ret[1:] = np.diff(close_arr) / close_arr[:-1]

    equity = 100.0; bnh = 100.0
    peak_eq = 100.0; peak_bh = 100.0
    mdd = 0.0; mdd_bh = 0.0
    eq_curve = [100.0]
    ret_list = []

    for i in range(1, n):
        r   = float(daily_ret[i])
        pos = float(pos_arr[i - 1])
        cost = (pos * 0.005 + (0.001 if pos > 0 else 0)) / 252
        pr = r * pos - cost
        equity *= (1 + pr); bnh *= (1 + r)
        peak_eq = max(peak_eq, equity); peak_bh = max(peak_bh, bnh)
        mdd    = max(mdd,    (peak_eq - equity) / peak_eq)
        mdd_bh = max(mdd_bh, (peak_bh - bnh)   / peak_bh)
        eq_curve.append(equity); ret_list.append(pr)

    years    = n / 252
    cagr     = float((equity / 100) ** (1 / years) - 1) if years > 0 else 0
    cagr_bh  = float((bnh   / 100) ** (1 / years) - 1) if years > 0 else 0
    arr = np.array(ret_list)
    sharpe = float(arr.mean() / arr.std() * np.sqrt(252)) if len(arr) > 1 and arr.std() > 0 else 0

    # 최근 5개년 연도별 수익률
    yearly = {}
    try:
        today_yr = _dt.date.today().year
        for yr_back in range(1, min(6, int(years) + 1)):
            end_i   = max(0, len(eq_curve) - (yr_back - 1) * 252 - 1)
            start_i = max(0, end_i - 252)
            if start_i < end_i and eq_curve[start_i] > 0:
                yr_ret = (eq_curve[end_i] / eq_curve[start_i] - 1) * 100
                yearly[str(today_yr - yr_back)] = round(yr_ret, 1)
    except Exception:
        pass

    return {
        "cagr":         round(cagr    * 100, 1),
        "mdd":          round(mdd     * 100, 1),
        "sharpe":       round(sharpe,  2),
        "years":        round(years,   1),
        "final_equity": round(equity,  1),
        "cagr_bh":      round(cagr_bh * 100, 1),
        "mdd_bh":       round(mdd_bh  * 100, 1),
        "yearly":       yearly,
    }


# ════════════════════════════════════════════════════════════════
# 텔레그램 메시지 포맷
# ════════════════════════════════════════════════════════════════
def fmt_price(val, ticker):
    if '^KS' in ticker or '^KQ' in ticker:
        return f"{val:,.1f}"
    elif '^N225' in ticker:
        return f"¥{val:,.0f}"
    elif '.SS' in ticker or '.SZ' in ticker:
        return f"¥{val:,.2f}"
    elif '^NSEI' in ticker or '^BSESN' in ticker:
        return f"₹{val:,.0f}"
    elif '^TWII' in ticker:
        return f"NT${val:,.0f}"
    elif '^AXJO' in ticker:
        return f"A${val:,.0f}"
    elif '^FTSE' in ticker:
        return f"£{val:,.0f}"
    elif '^FCHI' in ticker:
        return f"€{val:,.0f}"
    elif '^BVSP' in ticker:
        return f"R${val:,.0f}"
    elif '^STI' in ticker:
        return f"S${val:,.2f}"
    else:
        return f"${val:,.2f}"

def build_message(r):
    fp = lambda v: fmt_price(v, r['ticker'])
    sign = "+" if r['change_pct'] >= 0 else ""

    # 전략별 상세
    detail = ""
    if r['strategy'] == 'minervini':
        detail = (
            f"  📊 MA{r.get('ma_fast',0):,.0f} / {r.get('ma_slow',0):,.0f} | 기울기 {r.get('ma_slope',0):+.2f}%\n"
            f"  📈 RSI `{r['rsi']:.0f}` | ATR `{r.get('atr_pct',0):.1f}%`\n"
            f"  🎯 목표 {fp(r['target'])} (+{r['target_pct']:.1f}%)\n"
            f"  🛑 손절 {fp(r['stoploss'])} (-{r['stop_pct']:.1f}%)\n"
            f"  📏 R:R `{r['rr_ratio']:.1f}:1`\n"
        )
    elif r['strategy'] == 'leverage':
        lev = r.get('leverage', 1)
        etf_guide = ""
        if lev == 2.0:
            if '^KS' in r['ticker']: etf_guide = "KODEX 레버리지 (122630)"
            elif '^KQ' in r['ticker']: etf_guide = "KODEX 코스닥150 레버리지 (233740)"
            elif '^GSPC' in r['ticker'] or '^IXIC' in r['ticker']: etf_guide = "SSO(S&P) / QLD(나스닥)"
            elif '^NSEI' in r['ticker'] or '^BSESN' in r['ticker']: etf_guide = "INDL(2x인도) / Nifty BeES ETF"
        elif lev == 0:
            if '^KS' in r['ticker']: etf_guide = "현금 or KODEX 인버스 (114800)"
            elif '^KQ' in r['ticker']: etf_guide = "현금 or KODEX 코스닥150 인버스 (251340)"
        detail = (
            f"  ⚡ 레버리지: `{lev}x` {'🟢강세' if lev==2 else ('🔵보통' if lev==1 else '🔴현금')}\n"
            f"  📊 MA50 `{r.get('ma50',0):,.0f}` | MA200 `{r.get('ma200',0):,.0f}`\n"
            f"  📈 MA50기울기 `{r.get('ma50_slope',0):+.2f}%` | RSI `{r['rsi']:.0f}`\n"
            f"  {'⚠️ 변동성 급등!' if r.get('vol_spike') else ''}\n"
            f"{f'  💼 추천ETF: `{etf_guide}`' if etf_guide else ''}\n"
        )
    elif r['strategy'] == 'dual_filter':
        detail = (
            f"  📊 3개월 모멘텀: `{r.get('mom_3m',0):+.1f}%`\n"
            f"  📊 10개월 모멘텀: `{r.get('mom_10m',0):+.1f}%`\n"
            f"  📈 RSI `{r['rsi']:.0f}`\n"
            f"  💡 {'둘 다 음수 → 현금' if r.get('mom_3m',0)<0 and r.get('mom_10m',0)<0 else '하나라도 양수 → 투자유지'}\n"
        )
    elif r['strategy'] == 'risk_defense':
        detail = (
            f"  🛡️ 위험스코어: `{r.get('risk_score',0)}/100`\n"
            f"  📊 RSI `{r['rsi']:.0f}`\n"
            f"  ⚠️ 위험요인: {', '.join(r.get('risk_details',[])) or '없음'}\n"
        )

    return (
        f"{r['flag']} *{r['name']}* (`{r['symbol']}`)\n"
        f"  {r['signal']}\n"
        f"  전략: `{r.get('strategy_name','')}` | {r.get('strategy_label','')}\n\n"
        f"  💰 {fp(r['price'])} {sign}{r['change_pct']:.2f}%\n"
        f"  📈 고점대비 `{r['from_high_pct']:+.1f}%`\n"
        f"{detail}"
    )


# ════════════════════════════════════════════════════════════════
# 텔레그램 전송
# ════════════════════════════════════════════════════════════════
async def send_telegram(text):
    try:
        import telegram
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        for i in range(0, len(text), 4000):
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=text[i:i+4000],
                parse_mode=telegram.constants.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(1)
        print("  ✅ 텔레그램 전송 완료")
    except ImportError:
        print("  ⚠️ python-telegram-bot 미설치, 콘솔 출력만")
    except Exception as e:
        print(f"  🚫 전송 실패: {e}")


# ════════════════════════════════════════════════════════════════
# JSON 저장
# ════════════════════════════════════════════════════════════════
def save_json(results):
    export = {
        "generated_at": datetime.datetime.now().isoformat(),
        "version": "4.0",
        "markets": results,
    }
    path = os.path.join(OUTPUT_DIR, "signals_v4.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(export, f, ensure_ascii=False, indent=2, default=str)
    print(f"  📄 JSON: {path}")


# ════════════════════════════════════════════════════════════════
# 주식 검색 분석 — 헬퍼 함수들
# ════════════════════════════════════════════════════════════════
def _slope(series, n=5):
    """시리즈 n봉 기울기(변화율 %)"""
    s = series.dropna()
    if len(s) < n + 1:
        return 0.0
    v_now  = float(s.iloc[-1])
    v_prev = float(s.iloc[-(n + 1)])
    return (v_now - v_prev) / v_prev * 100 if v_prev != 0 else 0.0

# ── 공용 신호 매핑 (초기 산출과 모든 보정 이후 재산출에서 동일하게 사용) ──
SIG_TH = {"strong_buy": 80, "buy": 65, "sell": 35, "strong_sell": 20}

def score_to_signal(score):
    """0~100 점수(50=중립) → (signal_type, signal_text). 임계값 대칭."""
    if score >= SIG_TH["strong_buy"]:  return "STRONG_BUY",  "🟢 강력 매수"
    if score >= SIG_TH["buy"]:         return "BUY",         "🟢 매수"
    if score <= SIG_TH["strong_sell"]: return "STRONG_SELL", "🔴 강력 매도"
    if score <= SIG_TH["sell"]:        return "SELL",        "🔴 매도"
    return "NEUTRAL", "⚪ 중립"

def finalize_signal(score, gates=None):
    """점수 → 신호 매핑 + STRONG_* 게이트 적용 (게이트 미충족 시 한 단계 강등).
    초기 산출·KIS/DART 보정 후·서버 외부신호 보정 후 모두 이 함수로 재산출한다.

    강등 시 점수도 임계 경계(79/21)로 클램핑해 반환:
    점수 95인데 라벨은 '매수'(신뢰도 95)처럼 라벨-점수가 어긋나 보이는 문제 방지.
    반환: (signal_type, signal_text, score)"""
    sig, txt = score_to_signal(score)
    g = gates or {}
    if sig == "STRONG_BUY" and not g.get("strong_buy_ok", True):
        sig, txt = "BUY", "🟢 매수"
        score = min(score, SIG_TH["strong_buy"] - 1)   # 79
    elif sig == "STRONG_SELL" and not g.get("strong_sell_ok", True):
        sig, txt = "SELL", "🔴 매도"
        score = max(score, SIG_TH["strong_sell"] + 1)  # 21
    return sig, txt, int(score)

def conviction_from_score(score):
    """방향 무관 확신도(신뢰도) = max(score, 100-score).
    매수 계열은 점수 그대로, 매도 계열은 100-점수 → '강한 매도 = 높은 신뢰도'로 표시 일관성 확보.
    NEUTRAL은 50 근처(확신 낮음)로 자연 표현된다."""
    s = max(0, min(100, score))
    return int(round(max(s, 100 - s)))

def _interp(x, pts):
    """구간 선형 보간 — 임계값 절벽 제거용. pts: [(x0,y0),(x1,y1),...] x 오름차순."""
    if x <= pts[0][0]:
        return float(pts[0][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(pts[-1][1])

def _generate_signal(price, ma20, ma50, ma200, rsi, macd_hist, bb_pct_b, vol_ratio,
                       divergence=None, candle_pattern=None, ma50_slope=0,
                       rs_score=50, momentum_composite=50, vcp_detected=False,
                       market_env_adj=0, liquidity_adj=0, fundamental_adj=0,
                       chg_pct=0.0):
    """그룹 캡 기반 신호 점수 (0~100, 기준점 50 = 중립)

    설계 원칙:
      1) 상관 지표는 같은 그룹으로 묶어 합산 후 캡 → 이중카운팅 구조적 차단
      2) 이진 분기 대신 연속 점수(선형 보간/포화) → 임계값 절벽 제거
      3) 거래량은 단일 소스 + 당일 등락 방향 조건부 (급증·하락일은 감점)
      4) STRONG_* 는 점수 외에 독립 그룹 동방향 확인 게이트 필요

    그룹과 캡:
      추세     ±22 : price vs MA200/50/20 거리 + MA50 기울기
      모멘텀   ±15 : RSI(연속화, 과매도 보너스는 장기추세 생존 시에만) + MACD(가격 정규화)
      거래량   ±6  : vol_ratio 단일 소스 × 방향
      변동성   ±4  : 볼린저 %B
      패턴     ±10 : RSI 다이버전스 + 캔들
      상대강도 ±6  : RS 점수 연속화
      선행     +7/-3 : 모멘텀 복합 극단 + VCP
      시장환경 -12~+8 : regime+매크로 (호출부에서 합산해 전달, 여기서 캡)
      품질     ±10 : 유동성 + 펀더멘털

    신호: STRONG_BUY≥80(게이트), BUY≥65, NEUTRAL 36~64, SELL≤35, STRONG_SELL≤20(게이트)
    반환: (signal_type, signal_text, score, breakdown)
    """
    def _clip(v, lo, hi):
        return max(lo, min(hi, v))

    # ── 추세 그룹 (±22): MA 대비 % 거리의 포화 선형 점수 ──
    # 포화 거리를 넓게(10/7/4%) — 평범한 상승주가 그룹 만점을 즉시 채워
    # 점수 분포가 양극단에 뭉치던 문제 완화 (강한 추세일수록 점진적으로 가산)
    trend = 0.0
    if ma200 and ma200 > 0:
        trend += _clip((price / ma200 - 1) * 100 / 10.0, -1, 1) * 10   # ±10% 거리에서 포화
    if ma50 and ma50 > 0:
        trend += _clip((price / ma50 - 1) * 100 / 7.0, -1, 1) * 7
    if ma20 and ma20 > 0:
        trend += _clip((price / ma20 - 1) * 100 / 4.0, -1, 1) * 5
    trend += _clip(ma50_slope / 1.5, -1, 1) * 4
    trend = _clip(trend, -22, 22)

    # 장기추세 생존 여부 — 역추세 보너스(과매도/BB하단) 게이트
    long_trend_ok = (price > ma200) if (ma200 and ma200 > 0) else (ma50 and price > ma50)

    # ── 모멘텀 그룹 (±15): RSI 연속화 + MACD 히스토그램 ──
    # 과매도 보너스는 장기추세 위에서만 (하락추세 칼받기 보상 제거 → 매수편향 완화)
    rsi_pts = ([(20, 4), (30, 2), (45, 0), (55, 8), (65, 8), (70, -2), (80, -8), (90, -10)]
               if long_trend_ok else
               [(20, 0), (30, 0), (45, 0), (55, 6), (65, 8), (70, -2), (80, -8), (90, -10)])
    mom_rsi = _interp(rsi, rsi_pts)
    mom_macd = 0.0
    if price and macd_hist != 0:
        _macd_norm = (macd_hist / price) * 100          # 가격 대비 %
        mom_macd = _clip(_macd_norm / 0.5 * 6, -7, 7)   # 0.5% ≈ ±6점, 캡 ±7
    momentum = _clip(mom_rsi + mom_macd, -15, 15)

    # ── 거래량 그룹 (±6): 단일 소스 + 방향 조건부 ──
    # (기존: vol_ratio +5와 vol_z +5가 같은 데이터로 이중 가산 → 단일화)
    volume = 0.0
    if vol_ratio >= 1.5:
        v_mag = 3.0 + _clip((vol_ratio - 1.5) / 1.5, 0, 1) * 3.0   # 1.5x→3, 3x+→6
        volume = v_mag if chg_pct >= 0 else -v_mag                 # 급증+하락 = 투매 경계
    elif vol_ratio < 0.7:
        volume = -2.0                                              # 거래 위축 = 모멘텀 약화
    volume = _clip(volume, -6, 6)

    # ── 변동성 그룹 (±4): 볼린저 %B ──
    volat = 0.0
    if 0.3 <= bb_pct_b <= 0.7:
        volat = 2.0
    elif bb_pct_b > 0.95:
        volat = -4.0
    elif bb_pct_b > 0.85:
        volat = -2.0
    elif bb_pct_b < 0.05 and long_trend_ok:
        volat = 2.0   # 하단 반등 베팅도 장기추세 생존 시에만

    # ── 패턴 그룹 (±10) ──
    pattern = 0.0
    if divergence == "bullish":
        pattern += 7
    elif divergence == "bearish":
        pattern -= 7
    if candle_pattern in ("강세 장악형", "해머 (저점 반전)"):
        pattern += 4
    elif candle_pattern in ("약세 장악형", "슈팅스타 (고점 반전)"):
        pattern -= 4
    pattern = _clip(pattern, -10, 10)

    # ── 상대강도 (±6, 연속) ──
    rel = _clip((rs_score - 50) / 30.0, -1, 1) * 6

    # ── 선행 지표 ──
    leading = 0.0
    if momentum_composite >= 80:
        leading += 3
    elif momentum_composite <= 20:
        leading -= 3
    if vcp_detected:
        leading += 4

    # ── 시장환경(외부 합산) / 품질 그룹 캡 ──
    env     = _clip(market_env_adj, -12, 8)
    quality = _clip(liquidity_adj + fundamental_adj, -10, 10)

    score = 50 + trend + momentum + volume + volat + pattern + rel + leading + env + quality
    score = int(round(_clip(score, 0, 100)))

    # ── STRONG_* 게이트 ──────────────────────────────────────────
    # 점수만으로는 상관 지표 동시 점화 시 80을 쉽게 넘으므로, 독립 확인 요건을 추가:
    #  STRONG_BUY:  핵심 4그룹(추세·모멘텀·거래량·상대강도) 중 3개 동방향
    #               + 패턴 비역행 + (거래량 확인 또는 시장주도 RS≥70) ← 무거래 돌파 강등
    #  STRONG_SELL: 3개 동방향 + 패턴 비역행 + (투매 거래량 또는 시장 대비 뚜렷한 약세)
    core = (trend, momentum, volume, rel)
    bull_n = sum(1 for v in core if v > 1)
    bear_n = sum(1 for v in core if v < -1)
    gates = {
        "strong_buy_ok":  (bull_n >= 3 and pattern >= -3
                           and (volume > 1 or rel >= 4)),
        "strong_sell_ok": (bear_n >= 3 and pattern <= 3
                           and (volume < -1 or rel <= -4)),
    }
    breakdown = {
        "trend": round(trend, 1), "momentum": round(momentum, 1),
        "volume": round(volume, 1), "volatility": round(volat, 1),
        "pattern": round(pattern, 1), "rel_strength": round(rel, 1),
        "leading": round(leading, 1), "market_env": round(env, 1),
        "quality": round(quality, 1),
        "gates": gates,
    }
    signal_type, signal_text, score = finalize_signal(score, gates)
    return signal_type, signal_text, score, breakdown

def _generate_analysis_text(ticker, price, chg, rsi, macd_hist, bb_pct_b,
                              ma20, ma50, ma200, signal_type, vol_spike, from_high):
    """한국어 분석 문단 생성"""
    lines = []
    above = sum([price > ma20, price > ma50, price > (ma200 or 0)])
    if above == 3:
        lines.append("현재 가격이 20일·50일·200일 이동평균선 모두 위에 위치하여 강한 상승 추세를 보이고 있습니다.")
    elif above >= 2:
        lines.append("가격이 주요 이동평균선 위에 위치해 단기 상승 모멘텀이 유지되고 있습니다.")
    else:
        lines.append("가격이 주요 이동평균선 아래에 위치하여 하락 압력이 우세한 상황입니다.")

    rsi_desc  = f"RSI {rsi:.0f}로 과매수 구간, 단기 조정 가능성" if rsi > 70 else \
                f"RSI {rsi:.0f}로 과매도 구간, 기술적 반등 가능성" if rsi < 30 else \
                f"RSI {rsi:.0f}로 중립 구간"
    macd_desc = "MACD 히스토그램 양전환으로 매수 모멘텀 강화" if macd_hist > 0 else \
                "MACD 히스토그램 음전환으로 하락 모멘텀 진행 중"
    lines.append(f"{rsi_desc}이며, {macd_desc}입니다.")

    if vol_spike:
        lines.append("거래량이 20일 평균 대비 1.5배 이상 급증하여 강한 방향성 확인이 필요합니다.")
    elif bb_pct_b > 0.8:
        lines.append("볼린저밴드 상단 근처에 위치하여 단기 저항 구간에 접근 중입니다.")
    elif bb_pct_b < 0.2:
        lines.append("볼린저밴드 하단 근처에 위치하여 단기 과매도 반등 가능성이 있습니다.")
    else:
        fh_str = f"{abs(from_high):.1f}%" if from_high == from_high else "N/A"
        lines.append(f"52주 최고가 대비 {fh_str} 위치에 있으며 추세를 지속 모니터링할 필요가 있습니다.")
    return " ".join(lines)

def _generate_forecasts(price, signal_type, rsi, ma50_slope, macd_hist, bb_bw, from_high):
    """단기/중기/장기 전망 리스트 생성"""
    # 단기 (1주)
    if signal_type in ("STRONG_BUY", "BUY") and macd_hist > 0:
        short = {"label": "단기 (1주)", "outlook": "상승",  "color": "green",
                 "text": "MACD 매수 신호 유효, 단기 상승 모멘텀 지속 예상"}
    elif signal_type in ("STRONG_SELL", "SELL"):
        short = {"label": "단기 (1주)", "outlook": "하락",  "color": "red",
                 "text": "매도 압력 우세, 단기 조정 가능성 높음"}
    else:
        short = {"label": "단기 (1주)", "outlook": "중립",  "color": "yellow",
                 "text": "방향성 불분명, 관망 유지 권고"}
    # 중기 (1개월)
    if ma50_slope > 1.0:
        mid = {"label": "중기 (1개월)", "outlook": "상승", "color": "green",
               "text": "MA50 기울기 양호, 중기 추세 상승 기대"}
    elif ma50_slope < -1.0:
        mid = {"label": "중기 (1개월)", "outlook": "하락", "color": "red",
               "text": "MA50 하향, 중기 추세 약화 — 손절 관리 필요"}
    else:
        mid = {"label": "중기 (1개월)", "outlook": "중립", "color": "yellow",
               "text": "추세 전환 여부 지속 관찰 필요"}
    # 장기 (3개월)
    if from_high > -10 and signal_type in ("STRONG_BUY", "BUY"):
        long_ = {"label": "장기 (3개월)", "outlook": "상승", "color": "green",
                 "text": "고점 근접 + 강한 신호, 장기 상승 추세 유지 가능성 높음"}
    elif from_high < -30:
        long_ = {"label": "장기 (3개월)", "outlook": "회복", "color": "yellow",
                 "text": f"고점 대비 {abs(from_high):.0f}% 하락, 저가 매수 관심 구간 — 단 추세 확인 필요"}
    else:
        long_ = {"label": "장기 (3개월)", "outlook": "중립", "color": "yellow",
                 "text": "장기 추세 판단을 위한 추가 데이터 필요"}
    return [short, mid, long_]

def _assess_risk(price, ma20, ma50, ma200, rsi, bb_pct_b, vol_spike, from_high):
    """위험도 평가: score, level, color, factors"""
    factors, score = [], 0
    if ma200 and price < ma200: score += 25; factors.append("MA200 하회")
    if price < ma50:            score += 15; factors.append("MA50 하회")
    if rsi > 75:                score += 15; factors.append(f"RSI 과매수({rsi:.0f})")
    if rsi < 25:                score += 10; factors.append(f"RSI 과매도({rsi:.0f})")
    if vol_spike:               score += 10; factors.append("거래량 급증")
    if bb_pct_b > 0.9:          score += 10; factors.append("BB 상단 이탈")
    if from_high < -25:         score += 15; factors.append(f"고점대비 {from_high:.0f}%")
    level = "높음" if score >= 50 else "중간" if score >= 25 else "낮음"
    color = "red"   if score >= 50 else "yellow" if score >= 25 else "green"
    return {"score": score, "level": level, "color": color, "factors": factors}

def _build_price_history(df, n=20):
    """스파크라인용 가격 이력 (n개 균등 샘플)"""
    close = df['Close']
    idxs  = np.linspace(0, len(close) - 1, min(n, len(close)), dtype=int)
    return [{"d": df.index[i].strftime("%m/%d"), "c": round(float(close.iloc[i]), 2)} for i in idxs]


# ════════════════════════════════════════════════════════════════
# 개별 종목 백테스트
# ════════════════════════════════════════════════════════════════
def backtest_stock(ticker: str, period: str = "10y") -> dict | None:
    """개별 종목 백테스트 — 실제 전략 시뮬레이션.

    진입·청산 규칙 (카드에 보여주는 전략과 동일):
      - BUY/STRONG_BUY 시그널 → 종가 진입, calc_position_targets()로 stop/T2 설정
      - 당일 저가 ≤ stop  → 손절가에 청산
      - 당일 고가 ≥ T2   → 목표가에 청산
      - SELL/STRONG_SELL → 당일 종가 청산
      - 거래비용: 진입 0.15% + 청산 0.15% (왕복 0.3%)
    """
    import datetime as _dt

    df = load_data(ticker, period=period)
    if df is None or len(df) < 250:
        return None
    df = df.dropna(subset=['Close', 'High', 'Low', 'Open', 'Volume'])
    if len(df) < 250:
        return None

    close = df['Close']
    high  = df['High']
    low   = df['Low']
    n     = len(close)

    # 지표 사전 계산 (전체 기간 한번에)
    ma20_s  = close.rolling(20).mean()
    ma50_s  = close.rolling(50).mean()
    ma200_s = close.rolling(200).mean()
    rsi_s   = calc_rsi(close)
    ema12   = close.ewm(span=12, adjust=False).mean()
    ema26   = close.ewm(span=26, adjust=False).mean()
    _macd   = ema12 - ema26
    mhist_s = _macd - _macd.ewm(span=9, adjust=False).mean()
    bb_std  = close.rolling(20).std()
    bb_l    = close.rolling(20).mean() - 2 * bb_std
    bb_u    = close.rolling(20).mean() + 2 * bb_std
    bpctb_s = (close - bb_l) / (bb_u - bb_l).replace(0, np.nan)
    volr_s  = df['Volume'] / df['Volume'].rolling(20).mean().replace(0, np.nan)
    sl50_s  = (ma50_s - ma50_s.shift(5)) / ma50_s.shift(5).replace(0, np.nan) * 100
    atr_s   = calc_atr(df)
    low10_s = low.rolling(10).min()
    low20_s = low.rolling(20).min()
    high20_s= high.rolling(20).max()

    def _sig(i):
        c    = float(close.iloc[i])
        cp   = float(close.iloc[i-1]) if i > 0 else c
        m20  = float(ma20_s.iloc[i])  if not pd.isna(ma20_s.iloc[i])  else c
        m50  = float(ma50_s.iloc[i])  if not pd.isna(ma50_s.iloc[i])  else c
        m200 = float(ma200_s.iloc[i]) if not pd.isna(ma200_s.iloc[i]) else None
        rsi  = float(rsi_s.iloc[i])   if not pd.isna(rsi_s.iloc[i])   else 50
        mh   = float(mhist_s.iloc[i]) if not pd.isna(mhist_s.iloc[i]) else 0
        bpb  = float(bpctb_s.iloc[i]) if not pd.isna(bpctb_s.iloc[i]) else 0.5
        vr   = float(volr_s.iloc[i])  if not pd.isna(volr_s.iloc[i])  else 1.0
        s50  = float(sl50_s.iloc[i])  if not pd.isna(sl50_s.iloc[i])  else 0
        dchg = (c / cp - 1) * 100 if cp > 0 else 0.0
        sig, _, _, _ = _generate_signal(c, m20, m50, m200, rsi, mh, bpb, vr,
                                         ma50_slope=s50, chg_pct=dchg)
        return sig, m20, m50

    equity   = 100.0;  bnh      = 100.0
    peak_eq  = 100.0;  peak_bh  = 100.0
    mdd      = 0.0;    mdd_bh   = 0.0
    eq_curve = [100.0]; ret_list = []

    in_pos   = False
    stop_p   = 0.0
    target_p = 0.0
    FEE      = 0.0015   # 편도 수수료·세금

    for i in range(210, n):
        c      = float(close.iloc[i])
        c_hi   = float(high.iloc[i])
        c_lo   = float(low.iloc[i])
        c_prev = float(close.iloc[i - 1]) if i > 0 else c
        dr     = (c - c_prev) / c_prev if c_prev > 0 else 0

        # Buy & Hold 추적
        bnh    *= (1 + dr)
        peak_bh = max(peak_bh, bnh)
        mdd_bh  = max(mdd_bh, (peak_bh - bnh) / peak_bh)

        sig, m20, m50 = _sig(i)
        pr = 0.0  # 당일 포트폴리오 수익률 (현금 = 0)

        if in_pos:
            if c_lo <= stop_p:
                # 손절: 당일 저가가 손절가 이하 → 손절가에 청산
                pr = (stop_p / c_prev - 1) - FEE
                in_pos = False
            elif c_hi >= target_p:
                # 목표 달성: 당일 고가가 T2 이상 → 목표가에 청산
                pr = (target_p / c_prev - 1) - FEE
                in_pos = False
            elif sig in ("SELL", "STRONG_SELL"):
                # 매도 시그널: 종가 청산
                pr = dr - FEE
                in_pos = False
            else:
                # 보유 유지: mark-to-market
                pr = dr
        else:
            if sig in ("BUY", "STRONG_BUY"):
                # 신규 진입: 종가 매수, stop/target 설정
                atr  = float(atr_s.iloc[i])   if not pd.isna(atr_s.iloc[i])   else c * 0.02
                l10  = float(low10_s.iloc[i])  if not pd.isna(low10_s.iloc[i])  else c * 0.97
                l20  = float(low20_s.iloc[i])  if not pd.isna(low20_s.iloc[i])  else c * 0.95
                h20  = float(high20_s.iloc[i]) if not pd.isna(high20_s.iloc[i]) else c * 1.05
                tgts = calc_position_targets(c, atr, l20, h20, sig,
                                              ma20=m20, ma50=m50, low_10d=l10)
                if tgts and 0 < tgts["stop"] < c < tgts["t2"]:
                    in_pos   = True
                    stop_p   = tgts["stop"]
                    target_p = tgts["t2"]
                    pr = -FEE   # 진입 수수료만 당일 반영

        equity  *= (1 + pr)
        peak_eq  = max(peak_eq, equity)
        mdd      = max(mdd, (peak_eq - equity) / peak_eq)
        eq_curve.append(equity)
        ret_list.append(pr)

    years   = n / 252
    cagr    = float((equity / 100) ** (1 / years) - 1) if years > 0 else 0
    cagr_bh = float((bnh    / 100) ** (1 / years) - 1) if years > 0 else 0
    active  = [r for r in ret_list if r != 0.0]
    arr     = np.array(active)
    sharpe  = float(arr.mean() / arr.std() * np.sqrt(252)) if len(arr) > 10 and arr.std() > 0 else 0

    yearly = {}
    try:
        today_yr = _dt.date.today().year
        for yr_back in range(1, min(6, int(years) + 1)):
            end_i   = max(0, len(eq_curve) - (yr_back - 1) * 252 - 1)
            start_i = max(0, end_i - 252)
            if start_i < end_i and eq_curve[start_i] > 0:
                yearly[str(today_yr - yr_back)] = round(
                    (eq_curve[end_i] / eq_curve[start_i] - 1) * 100, 1)
    except Exception:
        pass

    return {
        "cagr":         round(cagr    * 100, 1),
        "mdd":          round(mdd     * 100, 1),
        "sharpe":       round(sharpe,  2),
        "years":        round(years,   1),
        "final_equity": round(equity,  1),
        "cagr_bh":      round(cagr_bh * 100, 1),
        "mdd_bh":       round(mdd_bh  * 100, 1),
        "yearly":       yearly,
    }


# ════════════════════════════════════════════════════════════════
# 선행 지표 헬퍼 함수들
# ════════════════════════════════════════════════════════════════
import time as _time_mod

_bm_close_cache: dict = {}  # {ticker: (timestamp, Series)}

def _get_benchmark_close(bm_ticker: str, period: str = "1y"):
    """벤치마크 종가 캐시 (1시간 TTL)
    캐시 키에 period 포함 — RS(1y)와 regime(2y)이 같은 키를 덮어써
    regime이 1y 데이터로 계산되던 버그 수정."""
    now = _time_mod.time()
    key = (bm_ticker, period)
    if key in _bm_close_cache:
        ts, series = _bm_close_cache[key]
        if now - ts < 3600:
            return series
    try:
        df_bm = load_data(bm_ticker, period=period)
        if df_bm.empty:
            return None
        series = df_bm['Close'].dropna()
        _bm_close_cache[key] = (now, series)
        return series
    except Exception:
        return None


def calc_relative_strength(close: pd.Series, bm_ticker: str) -> float:
    """상대강도 점수 (0~100). 50=시장평균, >50=시장 초과, <50=시장 미달"""
    bm_close = _get_benchmark_close(bm_ticker)
    if bm_close is None or len(close) < 63:
        return 50.0

    n6 = min(126, len(close), len(bm_close))
    n3 = min(63, n6)

    stk = close.values.astype(float)
    bm  = bm_close.values.astype(float)

    # 인덱스 불일치 방지: 각각 뒤에서 n개 슬라이싱
    stk_now = stk[-1];  stk_3 = stk[-n3];  stk_6 = stk[-n6]
    bm_now  = bm[-1];   bm_3  = bm[-n3];   bm_6  = bm[-n6]

    stk_ret3 = (stk_now / stk_3 - 1) if stk_3 != 0 else 0
    bm_ret3  = (bm_now  / bm_3  - 1) if bm_3  != 0 else 0
    stk_ret6 = (stk_now / stk_6 - 1) if stk_6 != 0 else 0
    bm_ret6  = (bm_now  / bm_6  - 1) if bm_6  != 0 else 0

    # 초과 수익률 (3개월 60%, 6개월 40% 가중)
    raw_rs = (stk_ret3 - bm_ret3) * 0.6 + (stk_ret6 - bm_ret6) * 0.4

    # ±30% 초과를 0~100으로 변환
    rs_score = 50.0 + raw_rs / 0.30 * 50.0
    return round(max(0.0, min(100.0, rs_score)), 1)


def calc_momentum_scores(close: pd.Series) -> dict:
    """1M/3M/6M 모멘텀 및 복합 점수"""
    c = close.dropna()
    n = len(c)
    curr = float(c.iloc[-1])

    def _ret(periods):
        if n < periods: return None
        base = float(c.iloc[-periods])
        return round((curr / base - 1) * 100, 1) if base != 0 else None

    mom_1m = _ret(21)
    mom_3m = _ret(63)
    mom_6m = _ret(126)

    parts, weights = [], []
    if mom_1m is not None: parts.append(mom_1m * 0.3); weights.append(0.3)
    if mom_3m is not None: parts.append(mom_3m * 0.4); weights.append(0.4)
    if mom_6m is not None: parts.append(mom_6m * 0.3); weights.append(0.3)

    if parts:
        raw = sum(parts) / sum(weights)
        composite = round(max(0.0, min(100.0, 50.0 + raw / 30.0 * 50.0)), 1)
    else:
        composite = 50.0

    return {"mom_1m": mom_1m, "mom_3m": mom_3m, "mom_6m": mom_6m, "composite": composite}


def detect_vcp(df: pd.DataFrame, high_52w: float) -> dict:
    """VCP (변동성 수축 패턴) 감지 — 미너비니 기준
    조건: ① 변동폭 수축 ② 거래량 수축 ③ 52주 고점 25% 이내
    """
    close = df['Close'].dropna()
    high  = df['High'].dropna()
    low   = df['Low'].dropna()
    vol   = df['Volume'].dropna()

    n = len(close)
    if n < 60:
        return {"detected": False, "stage": 0, "tightness": None, "dist_from_high_pct": None}

    current = float(close.iloc[-1])
    dist_from_high = (high_52w - current) / high_52w if high_52w > 0 else 1.0

    # 52주 고점에서 25% 이상 하락 시 VCP 미해당
    if dist_from_high > 0.25:
        return {"detected": False, "stage": 0, "tightness": None,
                "dist_from_high_pct": round(dist_from_high * 100, 1)}

    # 최근 60일을 3개 20일 구간으로 분할하여 range와 volume 측정
    segs = []
    for i in range(3):
        s = -(60 - i * 20)
        e = -(40 - i * 20) if i < 2 else None
        seg_h = float(high.iloc[s:e].max())
        seg_l = float(low.iloc[s:e].min())
        seg_v = float(vol.iloc[s:e].mean())
        rang  = (seg_h - seg_l) / seg_l * 100 if seg_l > 0 else 0
        segs.append({"range": rang, "vol": seg_v})
    # segs[0]=가장 오래된 구간 → segs[2]=최근 구간

    range_contracting = segs[0]["range"] > segs[1]["range"] > segs[2]["range"]
    vol_contracting   = segs[0]["vol"]   > segs[1]["vol"]   > segs[2]["vol"]

    # 최근 5일 tight 구간 (변동폭 5% 미만)
    last5_h = float(high.iloc[-5:].max())
    last5_l = float(low.iloc[-5:].min())
    last5_c = float(close.iloc[-5]) if n >= 5 else current
    recent_range_pct = (last5_h - last5_l) / last5_c * 100 if last5_c > 0 else 99
    very_tight = recent_range_pct < 5.0

    stage = sum([range_contracting, vol_contracting, very_tight])
    detected = stage >= 2

    return {
        "detected": detected,
        "stage": stage,
        "tightness": round(recent_range_pct, 1),
        "dist_from_high_pct": round(dist_from_high * 100, 1),
    }


def calc_market_regime(bm_ticker: str) -> dict:
    """벤치마크 추세로 시장 환경 평가
    - bull (강세장): 벤치마크가 MA200·MA50 모두 위 → +5점 (매수 신호 신뢰도 강화)
    - bear (약세장): 벤치마크가 MA200·MA50 모두 아래 → -10점 (역추세 매매 위험)
    - correction (상승장 조정): MA200 위 · MA50 아래 → 0점
    - rebound (약세장 반등): MA200 아래 · MA50 위 → -3점 (속임수 가능)
    """
    bm_close = _get_benchmark_close(bm_ticker, period="2y")
    if bm_close is None or len(bm_close) < 200:
        return {"regime": "unknown", "score_adj": 0,
                "bm_above_ma200": None, "bm_above_ma50": None,
                "bm_ticker": bm_ticker, "label": "데이터 부족"}

    bm_ma200 = float(bm_close.rolling(200).mean().iloc[-1])
    bm_ma50  = float(bm_close.rolling(50).mean().iloc[-1])
    bm_curr  = float(bm_close.iloc[-1])

    above_200 = bm_curr > bm_ma200
    above_50  = bm_curr > bm_ma50

    if above_200 and above_50:
        regime, adj, label = "bull",       +5,  "🟢 강세장"
    elif (not above_200) and (not above_50):
        regime, adj, label = "bear",       -10, "🔴 약세장"
    elif above_200 and (not above_50):
        regime, adj, label = "correction",  0,  "🟡 상승장 조정"
    else:
        regime, adj, label = "rebound",    -3,  "🟠 약세장 반등"

    return {
        "regime": regime, "score_adj": adj, "label": label,
        "bm_above_ma200": above_200, "bm_above_ma50": above_50,
        "bm_ticker": bm_ticker,
    }


def calc_liquidity_score(current_vol: int, price: float, is_korean: bool) -> dict:
    """거래대금(원화/달러) 기준 유동성 평가
    - 한국: 5억 미만 -5점 / 5억~20억 0점 / 20억 이상 +2점
    - 미국: $5M 미만 -5점 / $5M~$50M 0점 / $50M 이상 +2점
    """
    if current_vol is None or price is None or current_vol <= 0 or price <= 0:
        return {"score_adj": 0, "trading_value": 0, "label": "데이터 부족"}

    trading_value = current_vol * price  # 원화 또는 달러 단위

    if is_korean:
        low_th  = 500_000_000        # 5억 원
        high_th = 2_000_000_000      # 20억 원
        unit    = "억원"
        divisor = 1e8
    else:
        low_th  = 5_000_000          # $5M
        high_th = 50_000_000         # $50M
        unit    = "M$"
        divisor = 1e6

    if trading_value < low_th:
        adj, label = -5, f"⚠️ 저유동성"
    elif trading_value < high_th:
        adj, label = 0,  "보통"
    else:
        adj, label = 2,  "충분"

    return {
        "score_adj": adj,
        "trading_value": float(trading_value),
        "trading_value_display": f"{trading_value/divisor:.1f}{unit}",
        "label": label,
    }


def calc_fundamental_score(pe_ratio, roe, eps_growth) -> dict:
    """펀더멘털 점수 (±8점 캡)
    PER:      <10 +3, 10~25 +1, 25~50 0, ≥50 -2, None/음수 0
    ROE:      >20% +3, 15~20% +2, 10~15% +1, 0~10% 0, <0% -3
    EPS성장:  >30% +3, 15~30% +2, 0~15% +1, <0% -3
    """
    parts = []
    details = {}

    # PER
    if pe_ratio is not None:
        if   pe_ratio <= 0:   pe_pts = 0     # 적자기업 (PER 의미 없음)
        elif pe_ratio < 10:   pe_pts = 3
        elif pe_ratio < 25:   pe_pts = 1
        elif pe_ratio < 50:   pe_pts = 0
        else:                 pe_pts = -2
        parts.append(pe_pts); details["per"] = pe_pts
    else:
        details["per"] = None

    # ROE
    if roe is not None:
        if   roe >= 20:  roe_pts = 3
        elif roe >= 15:  roe_pts = 2
        elif roe >= 10:  roe_pts = 1
        elif roe >= 0:   roe_pts = 0
        else:            roe_pts = -3
        parts.append(roe_pts); details["roe"] = roe_pts
    else:
        details["roe"] = None

    # EPS 성장
    if eps_growth is not None:
        if   eps_growth >= 30: eps_pts = 3
        elif eps_growth >= 15: eps_pts = 2
        elif eps_growth >= 0:  eps_pts = 1
        else:                  eps_pts = -3
        parts.append(eps_pts); details["eps_growth"] = eps_pts
    else:
        details["eps_growth"] = None

    total = sum(parts) if parts else 0
    total = max(-8, min(8, total))   # 캡 ±8

    if   total >= 5:  label = "🟢 우량"
    elif total >= 2:  label = "🟢 양호"
    elif total >= -1: label = "🟡 보통"
    elif total >= -4: label = "🟠 부진"
    else:             label = "🔴 위험"

    return {"score_adj": total, "details": details, "label": label,
            "available": len(parts) > 0}


_macro_cache: dict = {}
_MACRO_TTL = 900   # 15분 — 전종목 랭킹 분석 시 종목마다 4개 심볼을 재다운로드하던 폭주 방지

def calc_macro_overlay(is_korean: bool = True) -> dict:
    """글로벌 매크로 — 공포지수(한국 ^VKOSPI / 미국 ^VIX), 미국 금리(TNX), 달러(DXY), 구리(HG=F)
    수정 사항:
      - 시장별 캐시(15분): 종목별 호출마다 yfinance 다운로드하던 성능 문제 해결
      - 공포지수를 시장에 맞게 분기: 기존엔 미국 종목에도 VKOSPI가 적용되던 버그
      - 캡 -12 ~ +8 (매크로 순풍 과대가산 방지, 역풍은 더 크게 — 의도된 보수성)
    반환: score_adj, details
    """
    import yfinance as yf, pandas as pd
    key = "kr" if is_korean else "us"
    now = _time_mod.time()
    cached = _macro_cache.get(key)
    if cached and now - cached["ts"] < _MACRO_TTL:
        return cached["data"]

    score = 0
    details: dict = {}
    fear_sym = "^VKOSPI" if is_korean else "^VIX"
    try:
        raw = yf.download([fear_sym, "^TNX", "DX-Y.NYB", "HG=F"],
                          period="1mo", interval="1d",
                          auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return {"score_adj": 0, "details": {}}
        cl = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw

        def _s(sym):
            try:
                s = cl[sym].dropna()
                return s if len(s) >= 2 else None
            except Exception:
                return None

        # 공포지수 (한국=VKOSPI 15/25/35, 미국=VIX 13/20/30 밴딩)
        s = _s(fear_sym)
        if s is not None:
            v = float(s.iloc[-1])
            lo, mid, hi = (15, 25, 35) if is_korean else (13, 20, 30)
            details["fear_index"] = round(v, 1)
            details["fear_symbol"] = fear_sym
            # 하위 호환 키 (기존 프론트가 vkospi 키를 읽음)
            details["vkospi"] = round(v, 1)
            if   v < lo:  score += 3;  details["vkospi_label"] = "안정"
            elif v < mid: score += 0;  details["vkospi_label"] = "보통"
            elif v < hi:  score -= 4;  details["vkospi_label"] = "불안"
            else:         score -= 10; details["vkospi_label"] = "공포"

        # 미국 10년물 금리
        s = _s("^TNX")
        if s is not None and len(s) >= 10:
            now_v, d10 = float(s.iloc[-1]), float(s.iloc[-10])
            chg = round(now_v - d10, 2)
            details["tnx"] = round(now_v, 2); details["tnx_chg"] = chg
            if   chg >  0.20: score -= 5; details["tnx_label"] = "급등↑"
            elif chg >  0.10: score -= 2; details["tnx_label"] = "상승"
            elif chg < -0.20: score += 3; details["tnx_label"] = "급락↓"
            elif chg < -0.10: score += 1; details["tnx_label"] = "하락"
            else:                          details["tnx_label"] = "보합"

        # 달러 인덱스 — 한국 종목 외국인 수급 영향 (한국 한정)
        if is_korean:
            s = _s("DX-Y.NYB")
            if s is not None and len(s) >= 10:
                now_v, d10 = float(s.iloc[-1]), float(s.iloc[-10])
                pct = round((now_v - d10) / d10 * 100, 1)
                details["dxy"] = round(now_v, 1); details["dxy_pct"] = pct
                if   pct >  1.0: score -= 4; details["dxy_label"] = "강세(외인매도↑)"
                elif pct >  0.4: score -= 2; details["dxy_label"] = "소폭강세"
                elif pct < -1.0: score += 3; details["dxy_label"] = "약세(외인유입↑)"
                elif pct < -0.4: score += 1; details["dxy_label"] = "소폭약세"
                else:                         details["dxy_label"] = "보합"

        # 구리 선물 (경기선행)
        s = _s("HG=F")
        if s is not None and len(s) >= 10:
            now_v, d10 = float(s.iloc[-1]), float(s.iloc[-10])
            pct = round((now_v - d10) / d10 * 100, 1)
            details["copper"] = round(now_v, 2); details["copper_pct"] = pct
            if   pct >  2.5: score += 2; details["copper_label"] = "급등(경기확장)"
            elif pct >  0.8: score += 1; details["copper_label"] = "상승"
            elif pct < -2.5: score -= 3; details["copper_label"] = "급락(경기우려)"
            elif pct < -0.8: score -= 1; details["copper_label"] = "하락"
            else:                         details["copper_label"] = "보합"
    except Exception:
        pass

    data = {"score_adj": max(-12, min(8, score)), "details": details}
    _macro_cache[key] = {"ts": now, "data": data}
    return data


def calc_volume_zscore(volume_series) -> dict:
    """20일 거래량 Z-score — 이상 거래 감지 (score_adj: +5 ~ -2)"""
    try:
        import pandas as pd
        vs = pd.Series(volume_series).dropna()
        if len(vs) < 22:
            return {"z": 0.0, "label": "데이터부족", "score_adj": 0}
        window = vs.iloc[-21:-1]
        mean_v, std_v = float(window.mean()), float(window.std())
        today_v = float(vs.iloc[-1])
        z = round((today_v - mean_v) / std_v, 2) if std_v > 0 else 0.0
        if   z >  3.0: adj, label = +5, f"폭증 +{z}σ"
        elif z >  2.0: adj, label = +3, f"급증 +{z}σ"
        elif z >  1.5: adj, label = +1, f"증가 +{z}σ"
        elif z < -1.5: adj, label = -2, f"감소 {z}σ"
        else:          adj, label =  0, f"보통 {z:.1f}σ"
        return {"z": z, "label": label, "score_adj": adj}
    except Exception:
        return {"z": 0.0, "label": "계산오류", "score_adj": 0}


# ════════════════════════════════════════════════════════════════
# 주식 검색 분석 — 메인 함수
# ════════════════════════════════════════════════════════════════
_fund_cache: dict = {}
_FUND_TTL = 21600   # 6시간 — yf.Ticker().info는 호출당 수 초 소요, 랭킹 전종목 분석 병목
_rt_price_cache: dict = {}
_RT_PRICE_TTL = 180  # 3분 — 장중 실시간 가격 캐시

def analyze_stock(ticker: str) -> dict:
    """
    개별 주식 기술적 분석 (한국/미국 모두 지원)
    ticker: 'AAPL', '005930.KS' 형식
    """
    df = load_data(ticker, period="1y")
    df = df.dropna(subset=['Close', 'High', 'Low', 'Open', 'Volume'])
    if df.empty or len(df) < 30:
        raise ValueError(f"데이터를 불러올 수 없습니다: {ticker}")

    # 펀더멘털 (PER, 시총, 배당, 베타, ROE, EPS성장) — 6시간 캐시
    pe_ratio = None;  market_cap = None;  dividend_yield = None
    beta = None;      roe = None;         eps_growth = None
    _fc = _fund_cache.get(ticker)
    if _fc and _time_mod.time() - _fc["ts"] < _FUND_TTL:
        f = _fc["data"]
        pe_ratio, market_cap, dividend_yield = f["pe"], f["mc"], f["dy"]
        beta, roe, eps_growth = f["beta"], f["roe"], f["eg"]
    else:
        try:
            t_obj = yf.Ticker(ticker)
            fi = t_obj.fast_info
            market_cap = getattr(fi, 'market_cap', None)
            full_info  = t_obj.info or {}
            pe_ratio   = full_info.get('trailingPE') or full_info.get('forwardPE')
            if pe_ratio and (pe_ratio < 0 or pe_ratio > 1000): pe_ratio = None
            dy = full_info.get('dividendYield')
            if dy and 0 < dy < 1:  dividend_yield = round(dy * 100, 2)  # 비율 → %
            elif dy and dy >= 1:   dividend_yield = round(dy, 2)        # 이미 % 형식
            beta = full_info.get('beta')
            if beta is not None: beta = round(float(beta), 2)
            roe_raw = full_info.get('returnOnEquity')
            if roe_raw: roe = round(float(roe_raw) * 100, 2)
            eg = full_info.get('earningsGrowth')
            if eg is not None: eps_growth = round(float(eg) * 100, 1)
            _fund_cache[ticker] = {"ts": _time_mod.time(), "data": {
                "pe": pe_ratio, "mc": market_cap, "dy": dividend_yield,
                "beta": beta, "roe": roe, "eg": eps_growth}}
        except Exception:
            pass

    close = df['Close']
    high  = df['High']
    low   = df['Low']

    current    = float(close.iloc[-1])
    prev       = float(close.iloc[-2]) if len(close) > 1 else current

    # 장중 실시간 가격 보정 (3분 캐시) — daily close는 장중 급등락을 반영 못 함
    try:
        _rt_now = _time_mod.time()
        _rt_cached = _rt_price_cache.get(ticker)
        if _rt_cached and _rt_now - _rt_cached["ts"] < _RT_PRICE_TTL:
            _rt_val = _rt_cached["price"]
        else:
            _rt_val = float(yf.Ticker(ticker).fast_info.last_price or 0)
            if _rt_val > 0:
                _rt_price_cache[ticker] = {"ts": _rt_now, "price": _rt_val}
        if _rt_val and _rt_val > 0 and abs(_rt_val - current) / current > 0.001:
            current = _rt_val
    except Exception:
        pass

    change_pct = (current - prev) / prev * 100
    change_abs = current - prev

    # 이동평균
    ma20  = float(close.rolling(20).mean().iloc[-1])
    ma50  = float(close.rolling(50).mean().iloc[-1])
    ma200_s = close.rolling(200).mean()
    ma200 = float(ma200_s.iloc[-1]) if not pd.isna(ma200_s.iloc[-1]) else None

    ma20_slope = _slope(close.rolling(20).mean())
    ma50_slope = _slope(close.rolling(50).mean())

    # RSI
    rsi = float(calc_rsi(close).iloc[-1])
    if pd.isna(rsi): rsi = 50.0

    # MACD
    macd_line, macd_sig, macd_hist = calc_macd(close)

    # 볼린저밴드
    bb_upper, bb_mid, bb_lower, bb_pct_b, bb_bw = calc_bollinger(close)

    # 거래량
    vol_ratio, vol_spike, vol_trend = calc_volume_analysis(df)
    current_vol = int(df['Volume'].iloc[-1])
    avg_vol     = int(df['Volume'].rolling(20).mean().iloc[-1]) if not pd.isna(df['Volume'].rolling(20).mean().iloc[-1]) else 0

    # 지지/저항
    low_10d    = float(low.rolling(10).min().iloc[-1])   # 스윙로우 (롱 손절 기준)
    high_10d   = float(high.rolling(10).max().iloc[-1])  # 스윙하이 (숏 손절 기준)
    support    = float(low.rolling(20).min().iloc[-1])
    resistance = float(high.rolling(20).max().iloc[-1])

    # 52주 범위
    high_52w  = float(high.max())
    low_52w   = float(low.min())
    from_high = (current - high_52w) / high_52w * 100

    # ATR (변동성, 손절가 산정)
    atr_series = calc_atr(df, p=14)
    atr_val    = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None

    # RSI 다이버전스
    rsi_series = calc_rsi(close)
    divergence = detect_rsi_divergence(close, rsi_series, lookback=20)

    # 캔들 패턴
    candle_pattern = detect_candle_pattern(df)

    # ── 선행 지표 ────────────────────────────────────────────────
    is_korean = ticker.endswith(".KS") or ticker.endswith(".KQ")
    bm_ticker = "^KS11" if is_korean else "^GSPC"

    rs_score = calc_relative_strength(close, bm_ticker)
    momentum = calc_momentum_scores(close)
    vcp      = detect_vcp(df, high_52w)

    # ── 매크로/품질 필터 ─────────────────────────────────────────
    regime      = calc_market_regime(bm_ticker)
    liquidity   = calc_liquidity_score(current_vol, current, is_korean)
    fundamental = calc_fundamental_score(pe_ratio, roe, eps_growth)
    macro       = calc_macro_overlay(is_korean)
    vol_z       = calc_volume_zscore(df["Volume"].values)

    # 시장환경 = regime + 매크로 합산 (한 그룹으로 캡 → 같은 '시장 상황'의 중복 가산 차단)
    market_env_adj = (regime["score_adj"] or 0) + (macro["score_adj"] or 0)

    # 신호 생성 (그룹 캡 점수 엔진) — vol_z는 점수에서 제외(표시용만), 거래량은 방향 조건부 단일 반영
    signal_type, signal_text, score, score_breakdown = _generate_signal(
        current, ma20, ma50, ma200, rsi, macd_hist, bb_pct_b, vol_ratio,
        divergence=divergence, candle_pattern=candle_pattern, ma50_slope=ma50_slope,
        rs_score=rs_score, momentum_composite=momentum["composite"],
        vcp_detected=vcp["detected"],
        market_env_adj=market_env_adj,
        liquidity_adj=liquidity["score_adj"],
        fundamental_adj=fundamental["score_adj"],
        chg_pct=change_pct,
    )

    # ── KIS Open API: 외국인·기관 순매수 + 체결강도 (한국 종목만) ──
    # 보정은 *점수(매수-매도 축)* 에 적용 — 신호와 신뢰도는 모든 보정 후 마지막에 한 번 재산출.
    # 비대칭 유지: 양의 보정은 +4 캡(과대평가 방지), 음의 페널티는 -12까지 (약점 발견용)
    kis_investor: dict = {}
    kis_trade:    dict = {}
    kis_score_adj: int = 0   # 점수 보정치 (양·음 모두 포함)
    if is_korean:
        try:
            from kis_api import get_investor_trend, get_trade_strength, is_available as _kis_ok
            if _kis_ok():
                krx_code     = ticker.split(".")[0]
                kis_investor = get_investor_trend(krx_code)
                kis_trade    = get_trade_strength(krx_code)
                # 외국인·기관 신호 보정 (양 +4 / 음 -8)
                sig = kis_investor.get("signal", "neutral")
                if   sig == "strong_buy":  kis_score_adj += 4    # 동반 매수: 확인 정도만 가산
                elif sig == "buy":         kis_score_adj += 2
                elif sig == "sell":        kis_score_adj -= 5
                elif sig == "strong_sell": kis_score_adj -= 8    # 동반 매도: 강한 경고 신호
                # 체결강도 보정 (양 +2 / 음 -4)
                cttr = kis_trade.get("cttr", 0)
                if   cttr >= 80: kis_score_adj += 2
                elif cttr >= 65: kis_score_adj += 1
                elif cttr <= 20: kis_score_adj -= 4
                elif cttr <= 35: kis_score_adj -= 2
                # 양의 가산은 캡 — 이미 점수가 높은 종목 과대평가 방지
                if kis_score_adj > 0:
                    if   score >= 90: kis_score_adj = 0
                    elif score >= 70: kis_score_adj = min(kis_score_adj, 3) // 2
                    else:             kis_score_adj = min(kis_score_adj, 5)
                score = max(0, min(100, score + kis_score_adj))
        except ImportError:
            pass
        except Exception:
            pass
    kis_conf_adj = kis_score_adj   # 출력용 별칭 (하위 호환)

    # 분석 텍스트
    analysis_text = _generate_analysis_text(
        ticker, current, change_pct, rsi, macd_hist, bb_pct_b,
        ma20, ma50, ma200, signal_type, vol_spike, from_high
    )
    # 보조 텍스트 추가 (다이버전스·캔들·선행지표·매크로)
    extras = []
    if divergence == "bullish":
        extras.append("⚡ RSI 상승 다이버전스 — 단기 반등 가능성")
    elif divergence == "bearish":
        extras.append("⚠️ RSI 하락 다이버전스 — 단기 조정 가능성")
    if candle_pattern:
        extras.append(f"🕯️ 직전봉: {candle_pattern}")
    if vcp["detected"]:
        extras.append(f"📐 VCP 패턴 감지 — 변동성 수축 {vcp['stage']}단계, 돌파 임박 가능성")
    if rs_score >= 70:
        extras.append(f"💪 RS {rs_score:.0f} — 시장 대비 강세 (상위 {100-int(rs_score)}%)")
    elif rs_score <= 30:
        extras.append(f"📉 RS {rs_score:.0f} — 시장 대비 약세")
    if regime["regime"] == "bear":
        extras.append(f"🌧️ 시장 환경 약세장 — 매수 신호 신뢰도 하향 조정")
    elif regime["regime"] == "bull":
        extras.append(f"☀️ 시장 환경 강세장 — 매수 신호 신뢰도 가중")
    if liquidity["score_adj"] < 0:
        extras.append(f"💧 거래대금 {liquidity.get('trading_value_display','')} — 저유동성 주의")
    if fundamental["available"] and fundamental["score_adj"] <= -4:
        extras.append(f"⚠️ 펀더멘털 부진 — 적자 또는 고평가 우려")
    elif fundamental["available"] and fundamental["score_adj"] >= 5:
        extras.append(f"🏅 펀더멘털 우량 — 저PER·고ROE·EPS성장 동반")
    # ── DART 임원 매매 (한국 종목만) ──────────────────────────
    dart_insider: dict = {}
    dart_disclosures: list = []
    if is_korean:
        try:
            from dart_api import get_insider_trades, get_recent_disclosures, is_available as _dart_ok
            if _dart_ok():
                krx_code = ticker.split(".")[0]
                dart_insider     = get_insider_trades(krx_code)
                dart_disclosures = get_recent_disclosures(krx_code)
                # 임원 매매 점수 보정 (비대칭: 양 +6 캡, 음 -6 풀)
                insider_adj = dart_insider.get("score_adj", 0)
                if insider_adj > 0 and score >= 80:
                    insider_adj = 0   # 이미 높은 종목 과대평가 방지
                score = max(0, min(100, score + insider_adj))
        except Exception:
            pass

    # ── 최종 신호·신뢰도 확정 ──────────────────────────────────
    # 모든 보정(KIS/DART)이 점수에 반영된 뒤 *한 번만* 신호를 재산출.
    # (기존: 보정으로 신뢰도만 바뀌고 신호 라벨은 그대로 → "강력매수 · 신뢰도 25" 모순 발생)
    signal_type, signal_text, score = finalize_signal(score, score_breakdown.get("gates"))
    confidence = conviction_from_score(score)   # 방향 무관 확신도 (매도도 강하면 높게 표시)

    # 손절/목표/R:R — 최종 신호 기준으로 산출 (기술적 지지선 + MA + 스윙로우/하이)
    targets = calc_position_targets(
        current, atr_val, support, resistance, signal_type,
        ma20=ma20, ma50=ma50, low_10d=low_10d, high_10d=high_10d
    )
    # 포지션 사이즈 (계좌 1천만원, 1% 리스크 가정 기본값)
    position = calc_position_size(current, targets["stop"], 10_000_000, 1.0) if targets else None

    # 거래량 Z-score extras
    if vol_z["score_adj"] >= 3:
        extras.append(f"📊 거래량 {vol_z['label']} — 이상 거래 감지")
    elif vol_z["score_adj"] <= -2:
        extras.append(f"📉 거래량 {vol_z['label']} — 관심 감소")

    # 글로벌 매크로 extras
    if macro["score_adj"] <= -8:
        mdet = macro["details"]
        parts = []
        if mdet.get("vkospi_label") == "공포":
            parts.append(f"VKOSPI {mdet.get('vkospi','?')}")
        if mdet.get("tnx_label","").startswith("급등"):
            parts.append(f"금리급등 +{mdet.get('tnx_chg','?')}%p")
        if mdet.get("dxy_label","").startswith("강세"):
            parts.append(f"달러강세 {mdet.get('dxy_pct','?')}%")
        if parts:
            extras.append(f"🌐 매크로 위험 — {' · '.join(parts)}")

    # DART 임원 매매 extras
    if dart_insider.get("net_signal") == "insider_buy":
        extras.append(f"👥 임원 매수 {dart_insider['buy_count']}건 (60일) — 강한 확신 신호")
    elif dart_insider.get("net_signal") == "insider_sell":
        extras.append(f"👥 임원 매도 {dart_insider['sell_count']}건 (60일) — 주의")

    # KIS 외국인·기관 순매수 코멘트 (한국 종목)
    if kis_investor:
        sig     = kis_investor.get("signal", "neutral")
        frgn_3d = kis_investor.get("frgn_3d", 0)
        inst_3d = kis_investor.get("inst_3d", 0)
        if sig in ("strong_buy", "buy") and frgn_3d > 0:
            parts = [f"외국인 3일 {frgn_3d:+,}주"]
            if inst_3d > 0: parts.append(f"기관 {inst_3d:+,}주")
            extras.append(f"🏦 KIS {' · '.join(parts)} 순매수")
        elif sig in ("strong_sell", "sell") and frgn_3d < 0:
            extras.append(f"🏦 KIS 외국인 3일 {frgn_3d:+,}주 순매도")
    if extras:
        analysis_text = analysis_text + " " + " ".join(extras)

    # 전망
    forecasts = _generate_forecasts(
        current, signal_type, rsi, ma50_slope, macd_hist, bb_bw, from_high
    )

    # 위험도
    risk = _assess_risk(current, ma20, ma50, ma200, rsi, bb_pct_b, vol_spike, from_high)

    # 스파크라인
    price_history = _build_price_history(df, n=20)

    # 메타 정보
    info = POPULAR_STOCKS.get(ticker, {})

    return {
        "ticker": ticker,
        "name": info.get("name", ticker),
        "name_en": info.get("name_en", ""),
        "sector": info.get("sector", ""),
        "flag": info.get("flag", "🌐"),
        "is_korean": is_korean,
        "price": round(current, 2),
        "change_abs": round(change_abs, 2),
        "change_pct": round(change_pct, 2),
        "volume": current_vol,
        "avg_volume": avg_vol,
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "from_high_pct": round(from_high, 1),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "ma200": round(ma200, 2) if ma200 else None,
        "ma20_slope": round(ma20_slope, 2),
        "ma50_slope": round(ma50_slope, 2),
        "rsi": round(rsi, 1),
        "macd_line": round(macd_line, 4),
        "macd_signal": round(macd_sig, 4),
        "macd_hist": round(macd_hist, 4),
        "bb_upper": round(bb_upper, 2),
        "bb_mid": round(bb_mid, 2),
        "bb_lower": round(bb_lower, 2),
        "bb_pct_b": bb_pct_b,
        "bb_bandwidth": bb_bw,
        "vol_ratio": vol_ratio,
        "vol_spike": vol_spike,
        "vol_trend": vol_trend,
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "signal_type": signal_type,
        "signal_text": signal_text,
        "score": score,                       # 매수-매도 축 점수 (0~100, 50=중립)
        "score_breakdown": score_breakdown,   # 그룹별 기여도 + STRONG_* 게이트
        "confidence": confidence,             # 방향 무관 확신도 = max(score, 100-score)
        "analysis_text": analysis_text,
        "forecasts": forecasts,
        "risk": risk,
        "price_history": price_history,
        # ── 펀더멘털 ──
        "pe_ratio": round(pe_ratio, 1) if pe_ratio else None,
        "market_cap": int(market_cap) if market_cap else None,
        "dividend_yield": dividend_yield,
        "beta": beta,
        "roe": roe,
        "eps_growth": eps_growth,
        # ── 진입/출구 전략 ──
        "atr": round(atr_val, 2) if atr_val else None,
        "targets": targets,
        "position": position,
        # ── 신호 보조 ──
        "divergence": divergence,
        "candle_pattern": candle_pattern,
        # ── 선행 지표 ──
        "rs_score": rs_score,
        "rs_label": "강세" if rs_score >= 70 else "약세" if rs_score <= 30 else "보통",
        "momentum": momentum,
        "vcp": vcp,
        # ── 매크로/품질 필터 ──
        "market_regime":    regime,
        "liquidity":        liquidity,
        "fundamental_score": fundamental,
        "macro_overlay":    macro,
        "vol_zscore":       vol_z,
        # ── DART 임원 매매 ──
        "dart_insider":     dart_insider,
        "dart_disclosures": dart_disclosures,
        # ── KIS 외국인·기관·체결강도 ──
        "kis_investor": kis_investor,
        "kis_trade":    kis_trade,
        "generated_at": datetime.datetime.now().isoformat(),
    }


# ════════════════════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════════════════════
async def main():
    start = datetime.datetime.now()
    now_str = start.strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*60}")
    print(f"  멀티마켓 통합 봇 v4.0 [{now_str}]")
    print(f"  {len(MARKETS)}개 시장 분석")
    print(f"{'='*60}")

    # 카테고리 분류
    categories = {
        "🪙 크립토":   [t for t,m in MARKETS.items() if 'USD' in t],
        "🇰🇷 한국 지수": [t for t,m in MARKETS.items() if '^KS' in t or '^KQ' in t],
        "🇺🇸 미국 지수": [t for t,m in MARKETS.items() if t in ('^GSPC','^IXIC','^DJI')],
        "🌏 일본/홍콩": [t for t,m in MARKETS.items() if t in ('^N225','^HSI')],
        "🇨🇳 중국":    [t for t,m in MARKETS.items() if '.SS' in t or '.SZ' in t],
        "🇮🇳 인도":    [t for t,m in MARKETS.items() if t in ('^NSEI','^BSESN')],
        "🌏 아시아기타": [t for t,m in MARKETS.items() if t in ('^TWII','^STI')],
        "🇪🇺 유럽":    [t for t,m in MARKETS.items() if t in ('^GDAXI','^FTSE','^FCHI')],
        "🌎 기타":     [t for t,m in MARKETS.items() if t in ('^AXJO','^BVSP')],
        "📊 변동성":   [t for t,m in MARKETS.items() if t in ('^VIX',)],
    }

    all_results = []

    for cat_name, tickers in categories.items():
        print(f"\n  {cat_name}")
        for ticker in tickers:
            info = MARKETS[ticker]
            print(f"    {info['flag']} {info['name']}...", end=" ")

            df = load_data(ticker, info.get('period', '2y'))
            if df.empty:
                print("⚠️ 데이터 없음")
                continue

            r = analyze_market(ticker, info, df)
            if r:
                all_results.append(r)
                print(f"{r['signal']}")
            else:
                print("⚠️ 분석 실패")

            gc.collect()

    # JSON 저장
    save_json(all_results)

    # ── 골든/데드크로스 특별 알림 ──
    cross_alerts = []
    for r in all_results:
        cs = r.get("cross_signal", "none")
        if cs == "golden":
            cross_alerts.append(f"🌟 *골든크로스* {r['flag']} {r['name']} (MA50↑MA200)")
        elif cs == "dead":
            cross_alerts.append(f"💀 *데드크로스* {r['flag']} {r['name']} (MA50↓MA200)")
    if cross_alerts:
        alert_msg = "⚡ *크로스 신호 발생!*\n" + "\n".join(cross_alerts)
        await send_telegram(alert_msg)

    # 텔레그램 메시지 구성
    elapsed = (datetime.datetime.now() - start).seconds
    header = (
        f"🔔 *멀티마켓 통합 봇 v4.0*\n"
        f"📅 {now_str} ({elapsed}초)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"크립토: 미너비니 | 지수: 레버리지/모멘텀/위기방어\n"
        f"5년 실데이터 백테스트 검증 완료\n"
    )

    parts = [header]

    for cat_name, tickers in categories.items():
        cat_results = [r for r in all_results if r['ticker'] in tickers]
        if not cat_results:
            continue
        parts.append(f"\n{'━'*21}\n{cat_name}\n")
        for r in cat_results:
            parts.append(build_message(r))
            parts.append(f"{'─'*21}\n")

    # 요약 테이블
    parts.append(f"\n{'━'*21}\n📊 *요약*\n")
    for r in all_results:
        sig_icon = "🟢" if "BUY" in r.get('signal_type','') or "2X" in r.get('signal_type','') or r.get('signal_type')=='INVESTED' \
                   else ("🔴" if "CASH" in r.get('signal_type','') or "SELL" in r.get('signal_type','') \
                   else "⚪")
        lev_str = f" {r['leverage']}x" if 'leverage' in r else ""
        parts.append(f"  {r['flag']}{r['symbol']:<8} {sig_icon}{lev_str} {r.get('strategy_name','')[:6]}\n")

    parts.append(f"\n⏰ 다음: 매일 08:00 / 20:00 KST")

    full_msg = "".join(parts)

    # 텔레그램 전송
    await send_telegram(full_msg)

    # 콘솔 요약
    print(f"\n{'='*60}")
    print(f"  완료! {len(all_results)}개 시장")
    print(f"{'─'*60}")
    for r in all_results:
        sig_icon = "🟢" if "BUY" in r.get('signal_type','') or "2X" in r.get('signal_type','') or r.get('signal_type')=='INVESTED' \
                   else ("🔴" if "CASH" in r.get('signal_type','') or "SELL" in r.get('signal_type','') \
                   else "⚪")
        print(f"  {r['flag']} {r['name']:<12} {sig_icon} {r['signal']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())


