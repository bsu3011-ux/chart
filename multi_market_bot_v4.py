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
    # ── BTC 현물: 위기방어형 (5년 실데이터 +112%, MDD -38%, 승률80%, PF 4.3) ──
    "BTC-USD": {
        "name": "비트코인", "symbol": "BTC", "flag": "₿",
        "strategy": "risk_defense",
        "params": {"check_interval":5, "is_crypto":True},
        "period": "1y",
    },
    # ── ETH 현물: 미너비니 타이트 (5년 실데이터 +135%, MDD -48%, PF 1.9) ──
    "ETH-USD": {
        "name": "이더리움", "symbol": "ETH", "flag": "Ξ",
        "strategy": "minervini",
        "params": {"ma_fast":10,"ma_slow":21,"entry_rsi":40,
                   "exit_buffer_atr":1.0,"trailing_atr":3.0,
                   "hard_stop_pct":0.10,"cooldown_days":2},
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
    # ── 일본/홍콩: 이중필터 모멘텀 (NIKKEI +103%, 항셍 +25%) ──
    "^N225": {
        "name": "Nikkei 225", "symbol": "NKI", "flag": "🇯🇵",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    "^HSI": {
        "name": "항셍지수", "symbol": "HSI", "flag": "🇭🇰",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 유럽: 위기방어형 (DAX +58%) ──
    "^GDAXI": {
        "name": "DAX", "symbol": "DAX", "flag": "🇩🇪",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 미국: DOW (위기방어형, MDD 관리) ──
    "^DJI": {
        "name": "다우존스", "symbol": "DJI", "flag": "🇺🇸",
        "strategy": "risk_defense",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 중국: 상해종합 (이중필터 모멘텀) ──
    "000001.SS": {
        "name": "상해종합", "symbol": "SSE", "flag": "🇨🇳",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 중국: 심천성분 (이중필터 모멘텀) ──
    "399001.SZ": {
        "name": "심천성분", "symbol": "SZSE", "flag": "🇨🇳",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 인도: NIFTY 50 (레버리지 — 강한 성장 시장) ──
    "^NSEI": {
        "name": "NIFTY 50", "symbol": "NIF", "flag": "🇮🇳",
        "strategy": "leverage",
        "params": {"check_interval":5},
        "period": "2y",
    },
    # ── 인도: Sensex (이중필터 모멘텀) ──
    "^BSESN": {
        "name": "Sensex", "symbol": "BSE", "flag": "🇮🇳",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 대만: 가권지수 (이중필터 모멘텀) ──
    "^TWII": {
        "name": "대만 가권", "symbol": "TWI", "flag": "🇹🇼",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
        "period": "2y",
    },
    # ── 호주: ASX 200 (위기방어형) ──
    "^AXJO": {
        "name": "ASX 200", "symbol": "ASX", "flag": "🇦🇺",
        "strategy": "risk_defense",
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
    # ── 브라질: Bovespa (이중필터 모멘텀) ──
    "^BVSP": {
        "name": "Bovespa", "symbol": "BVSP", "flag": "🇧🇷",
        "strategy": "dual_filter",
        "params": {"rebal_days":21},
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
    # ── 유로 스탁스 50 ──
    "^STOXX50E": {
        "name": "Euro Stoxx 50", "symbol": "SX5E", "flag": "🇪🇺",
        "strategy": "risk_defense",
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
    "000100.KS": {"name": "유한양행",      "name_en": "Yuhan Corp",           "sector": "제약",      "flag": "🇰🇷"},
    "128940.KS": {"name": "한미약품",      "name_en": "Hanmi Pharm",          "sector": "제약",      "flag": "🇰🇷"},
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
    target = current + _atr * (3.0 if is_stage2 else 2.0)

    risk = current - stoploss
    reward = target - current
    rr = reward / risk if risk > 0 else 0
    if rr < 2.0 and risk > 0:
        target = current + risk * 2.0
        rr = 2.0

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
def analyze_leverage(df, params):
    close = df['Close']
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    rsi = calc_rsi(close)
    vol20 = close.pct_change().rolling(20).std()
    vol60 = close.pct_change().rolling(60).std()

    i = len(df) - 1
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    _ma50 = float(ma50.iloc[-1]) if not pd.isna(ma50.iloc[-1]) else current
    _ma200 = float(ma200.iloc[-1]) if not pd.isna(ma200.iloc[-1]) else current
    _rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    _v20 = float(vol20.iloc[-1]) if not pd.isna(vol20.iloc[-1]) else 0.01
    _v60 = float(vol60.iloc[-1]) if not pd.isna(vol60.iloc[-1]) else 0.01

    slope50 = 0
    if i >= 5 and not pd.isna(ma50.iloc[i-5]):
        slope50 = (float(ma50.iloc[i]) - float(ma50.iloc[i-5])) / float(ma50.iloc[i-5]) * 100

    vol_spike = _v20 > _v60 * 1.5 if _v60 > 0 else False

    # 골든크로스 / 데드크로스 감지
    cross_signal = "none"
    if i >= 1 and not pd.isna(ma50.iloc[-2]) and not pd.isna(ma200.iloc[-2]):
        prev_ma50  = float(ma50.iloc[-2])
        prev_ma200 = float(ma200.iloc[-2])
        if prev_ma50 < prev_ma200 and _ma50 >= _ma200:
            cross_signal = "golden"   # 골든크로스 발생!
        elif prev_ma50 > prev_ma200 and _ma50 <= _ma200:
            cross_signal = "dead"     # 데드크로스 발생!
        elif _ma50 > _ma200:
            cross_signal = "bull"     # 골든크로스 유지
        else:
            cross_signal = "bear"     # 데드크로스 유지

    # 레버리지 결정
    if current > _ma50 and slope50 > 0 and _rsi > 50 and not vol_spike:
        lev = 2.0
        signal = "🟢 2x 레버리지"
        signal_type = "LEVERAGE_2X"
    elif current > _ma200:
        lev = 1.0
        signal = "🔵 1x 원물"
        signal_type = "HOLD_1X"
    elif current < _ma200:
        lev = 0.0
        signal = "🔴 현금 전환"
        signal_type = "CASH"
    else:
        lev = 1.0
        signal = "⚪ 1x 원물"
        signal_type = "HOLD_1X"

    if vol_spike and current < _ma50:
        lev = 0.0
        signal = "🔴 현금 (변동성 급등)"
        signal_type = "CASH_VOL"

    return {
        "signal": signal, "signal_type": signal_type,
        "leverage": lev,
        "price": current, "change_pct": (current-prev)/prev*100,
        "ma50": _ma50, "ma200": _ma200, "ma50_slope": slope50,
        "rsi": _rsi, "vol_spike": vol_spike,
        "cross_signal": cross_signal,
        "strategy_name": "레버리지 스위칭",
        "strategy_label": f"2x/1x/0x (MA50/200)",
    }


# ════════════════════════════════════════════════════════════════
# 전략 3: 이중필터 모멘텀 (NIKKEI/항셍용)
# ════════════════════════════════════════════════════════════════
def analyze_dual_filter(df, params):
    close = df['Close']
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    rsi_val = float(calc_rsi(close).iloc[-1])

    mom_3m = (current / float(close.iloc[-63]) - 1) * 100 if len(close) >= 63 else 0
    mom_10m = (current / float(close.iloc[-210]) - 1) * 100 if len(close) >= 210 else 0

    both_neg = mom_3m < 0 and mom_10m < 0
    any_pos = mom_3m > 0 or mom_10m > 0

    if both_neg:
        signal = "🔴 현금 (3m & 10m 모두 음)"
        signal_type = "CASH"
        action = "현금 전환"
    elif any_pos:
        signal = "🟢 투자 유지"
        signal_type = "INVESTED"
        action = "투자 유지"
    else:
        signal = "⚪ 관망"
        signal_type = "NEUTRAL"
        action = "관망"

    return {
        "signal": signal, "signal_type": signal_type,
        "price": current, "change_pct": (current-prev)/prev*100,
        "mom_3m": round(mom_3m, 2), "mom_10m": round(mom_10m, 2),
        "rsi": rsi_val,
        "action": action,
        "strategy_name": "이중필터 모멘텀",
        "strategy_label": f"3m({mom_3m:+.1f}%) + 10m({mom_10m:+.1f}%)",
    }


# ════════════════════════════════════════════════════════════════
# 전략 4: 위기방어형 (DAX + BTC 현물용)
# ════════════════════════════════════════════════════════════════
def analyze_risk_defense(df, params):
    close = df['Close']
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    rsi = calc_rsi(close)
    # 크립토는 365일 기준, 주식은 252일 기준 연환산
    ann_factor = np.sqrt(365) if params.get('is_crypto') else np.sqrt(252)
    vol20 = close.pct_change().rolling(20).std() * ann_factor * 100
    vol60 = close.pct_change().rolling(60).std() * ann_factor * 100

    i = len(df) - 1
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    _ma50 = float(ma50.iloc[-1]) if not pd.isna(ma50.iloc[-1]) else current
    _ma200 = float(ma200.iloc[-1]) if not pd.isna(ma200.iloc[-1]) else current
    _rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
    _v20 = float(vol20.iloc[-1]) if not pd.isna(vol20.iloc[-1]) else 20
    _v60 = float(vol60.iloc[-1]) if not pd.isna(vol60.iloc[-1]) else 20
    r20 = (current / float(close.iloc[i-20]) - 1) * 100 if i >= 20 else 0

    # 크립토는 변동성이 크므로 20일 하락 임계값을 -10%로 (주식은 -5%)
    drop_threshold = -10 if params.get('is_crypto') else -5

    risk_score = 0
    risk_details = []
    if current < _ma200:  risk_score += 30; risk_details.append("MA200↓")
    if current < _ma50:   risk_score += 15; risk_details.append("MA50↓")
    if _ma50 < _ma200:    risk_score += 15; risk_details.append("데드크로스")
    if _rsi < 40:         risk_score += 10; risk_details.append(f"RSI{_rsi:.0f}")
    if r20 < drop_threshold: risk_score += 15; risk_details.append(f"20일{r20:.1f}%")
    if _v20 > _v60 * 1.5: risk_score += 15; risk_details.append("변동성↑")

    if risk_score >= 70:
        signal = f"🔴 현금 전환 (위험 {risk_score}점)"
        signal_type = "CASH"
    elif risk_score >= 50:
        signal = f"🟡 주의 (위험 {risk_score}점)"
        signal_type = "CAUTION"
    elif risk_score <= 30:
        signal = f"🟢 투자 유지 (위험 {risk_score}점)"
        signal_type = "INVESTED"
    else:
        signal = f"⚪ 관망 (위험 {risk_score}점)"
        signal_type = "NEUTRAL"

    return {
        "signal": signal, "signal_type": signal_type,
        "risk_score": risk_score, "risk_details": risk_details,
        "price": current, "change_pct": (current-prev)/prev*100,
        "rsi": _rsi,
        "strategy_name": "위기방어형",
        "strategy_label": f"위험스코어 {risk_score}/100",
    }


# ════════════════════════════════════════════════════════════════
# 통합 분석 라우터
# ════════════════════════════════════════════════════════════════
def analyze_market(ticker, market_info, df):
    strategy = market_info["strategy"]
    params = market_info["params"]

    if strategy == "minervini":
        result = analyze_minervini(df, params)
    elif strategy == "leverage":
        result = analyze_leverage(df, params)
    elif strategy == "dual_filter":
        result = analyze_dual_filter(df, params)
    elif strategy == "risk_defense":
        result = analyze_risk_defense(df, params)
    else:
        return None

    # 공통 필드 추가
    close = df['Close']
    result.update({
        "ticker": ticker,
        "name": market_info["name"],
        "symbol": market_info["symbol"],
        "flag": market_info["flag"],
        "strategy": strategy,
        "high_1y": float(df['High'].max()),
        "low_1y": float(df['Low'].min()),
        "from_high_pct": round((result['price'] - float(df['High'].max())) / float(df['High'].max()) * 100, 1),
        "price_history": _build_price_history(df, n=20),
    })
    return result


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

def _generate_signal(price, ma20, ma50, ma200, rsi, macd_hist, bb_pct_b, vol_ratio):
    """7개 조건 기반 복합 신호"""
    score = 0
    if price > ma20:                  score += 1
    if price > ma50:                  score += 1
    if ma200 and price > ma200:       score += 1
    if 50 < rsi < 70:                 score += 1
    if macd_hist > 0:                 score += 1
    if bb_pct_b > 0.5:                score += 1
    if vol_ratio > 1.2:               score += 1
    if score >= 6: return "STRONG_BUY",  "🟢 강력 매수"
    if score >= 4: return "BUY",         "🟢 매수"
    if score <= 1: return "STRONG_SELL", "🔴 강력 매도"
    if score <= 3: return "SELL",        "🔴 매도"
    return "NEUTRAL", "⚪ 중립"

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
        lines.append(f"52주 최고가 대비 {abs(from_high):.1f}% 위치에 있으며 추세를 지속 모니터링할 필요가 있습니다.")
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
# 주식 검색 분석 — 메인 함수
# ════════════════════════════════════════════════════════════════
def analyze_stock(ticker: str) -> dict:
    """
    개별 주식 기술적 분석 (한국/미국 모두 지원)
    ticker: 'AAPL', '005930.KS' 형식
    """
    df = load_data(ticker, period="1y")
    if df.empty or len(df) < 30:
        raise ValueError(f"데이터를 불러올 수 없습니다: {ticker}")

    close = df['Close']
    high  = df['High']
    low   = df['Low']

    current    = float(close.iloc[-1])
    prev       = float(close.iloc[-2]) if len(close) > 1 else current
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
    support    = float(low.rolling(20).min().iloc[-1])
    resistance = float(high.rolling(20).max().iloc[-1])

    # 52주 범위
    high_52w  = float(high.max())
    low_52w   = float(low.min())
    from_high = (current - high_52w) / high_52w * 100

    # 신호 생성
    signal_type, signal_text = _generate_signal(
        current, ma20, ma50, ma200, rsi, macd_hist, bb_pct_b, vol_ratio
    )

    # 분석 텍스트
    analysis_text = _generate_analysis_text(
        ticker, current, change_pct, rsi, macd_hist, bb_pct_b,
        ma20, ma50, ma200, signal_type, vol_spike, from_high
    )

    # 전망
    forecasts = _generate_forecasts(
        current, signal_type, rsi, ma50_slope, macd_hist, bb_bw, from_high
    )

    # 위험도
    risk = _assess_risk(current, ma20, ma50, ma200, rsi, bb_pct_b, vol_spike, from_high)

    # 스파크라인
    price_history = _build_price_history(df, n=20)

    # 메타 정보
    info       = POPULAR_STOCKS.get(ticker, {})
    is_korean  = ticker.endswith(".KS") or ticker.endswith(".KQ")

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
        "analysis_text": analysis_text,
        "forecasts": forecasts,
        "risk": risk,
        "price_history": price_history,
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
