"""
백테스트 비교: (A) 현재 설정된 투자법 vs (B) 신고가근접+거래량5배+실적우상향 3단계 스크리닝

⚠️ 반드시 운영서버(yfinance 접근 가능한 곳)에서 실행할 것.
   사용법: python3 backtest_compare.py [샘플종목수=40] [기간=6y]

방법론 (정직하게 명시):
  A) backtest_stock() 그대로 재사용 — 카드에 보이는 것과 동일한 BUY/SELL 시그널
     진입/청산 룰로 시뮬레이션. (이미 존재하는 검증된 백테스트 엔진)

  B) 3단계 스크리닝:
     1. 신고가 근접: 종가가 직전 252일 최고가의 97% 이상
     2. 거래량 5배 이상: 당일 거래량 / 20일 평균거래량 >= 5
     3. 실적 우상향: 최근 분기 매출/영업이익이 직전 분기 대비 개선
        (yfinance 분기 재무제표는 "현재 시점" 데이터만 제공 — 과거 특정 일자의
         실적 발표 시점 데이터를 가져올 수 없음. 따라서 이 필터는 종목 단위로
         "현재 펀더멘털이 우상향 중인 종목"만 골라낸 뒤, 그 종목의 과거 가격사상
         에서 1+2 조건이 맞았던 날짜들을 진입 시점으로 사용하는 근사 방식임.
         완전한 point-in-time 백테스트가 아니라는 점을 감안해서 결과를 해석할 것.)
     진입: 트리거 발생 다음날 시가 매수. 청산: 20거래일 보유 후 종가 청산,
     또는 보유중 종가가 -8% 이하로 하락하면 즉시 손절. 왕복 수수료 0.3%.
     중복진입 방지(보유 중엔 신규 신호 무시).
"""
import sys
import random
import numpy as np
import pandas as pd

import multi_market_bot_v4 as bot

FEE = 0.0015          # 편도
STOP_PCT = 0.08        # 손절 -8%
HOLD_DAYS = 20          # 고정 보유일
NEAR_HIGH_PCT = 0.97    # 52주 고점의 97% 이상
VOL_SURGE_MULT = 5.0    # 거래량 5배


def fundamental_uptrend(ticker: str) -> bool | None:
    """최근 분기 매출/영업이익이 직전 분기 대비 개선됐는지. 데이터 없으면 None."""
    try:
        t = bot.yf.Ticker(ticker)
        qf = t.quarterly_financials
        if qf is None or qf.empty:
            return None
        rev_row = next((r for r in qf.index if "Total Revenue" in r), None)
        oi_row = next((r for r in qf.index if "Operating Income" in r), None)
        if rev_row is None or oi_row is None:
            return None
        rev = qf.loc[rev_row].dropna()
        oi = qf.loc[oi_row].dropna()
        if len(rev) < 2 or len(oi) < 2:
            return None
        rev_up = float(rev.iloc[0]) > float(rev.iloc[1])
        oi_up = float(oi.iloc[0]) > float(oi.iloc[1])
        return bool(rev_up and oi_up)
    except Exception:
        return None


def backtest_screen_b(ticker: str, period: str = "6y") -> dict | None:
    df = bot.load_data(ticker, period=period)
    if df is None or len(df) < 280:
        return None
    df = df.dropna(subset=["Close", "High", "Low", "Open", "Volume"])
    if len(df) < 280:
        return None

    if fundamental_uptrend(ticker) is not True:
        return None  # 실적 우상향 조건 불충족(또는 데이터 없음) → 이 종목은 스크리닝 통과 못함

    close = df["Close"].values.astype(float)
    high = df["High"].values.astype(float)
    low = df["Low"].values.astype(float)
    open_ = df["Open"].values.astype(float)
    vol = df["Volume"].values.astype(float)
    n = len(close)

    roll_high_252 = pd.Series(close).rolling(252).max().values
    vol_avg20 = pd.Series(vol).rolling(20).mean().values

    equity = 100.0
    peak_eq = 100.0
    mdd = 0.0
    eq_curve = [100.0]
    ret_list = []
    trades = []

    in_pos = False
    entry_i = -1
    entry_price = 0.0

    for i in range(252, n):
        pr = 0.0
        if in_pos:
            held = i - entry_i
            if held == 0:
                # 진입 당일: 시가 매수 → 종가 마감 + 진입수수료
                pr = close[i] / entry_price - 1 - FEE
            else:
                pr = close[i] / close[i - 1] - 1   # 보유중 mark-to-market
            stop_hit = close[i] <= entry_price * (1 - STOP_PCT)
            time_up = held >= HOLD_DAYS
            if stop_hit or time_up:
                pr -= FEE   # 청산수수료
                trades.append(close[i] / entry_price - 1)
                in_pos = False
        else:
            near_high = (not np.isnan(roll_high_252[i])) and close[i] >= roll_high_252[i] * NEAR_HIGH_PCT
            vol_surge = (not np.isnan(vol_avg20[i])) and vol_avg20[i] > 0 and (vol[i] / vol_avg20[i]) >= VOL_SURGE_MULT
            if near_high and vol_surge and i + 1 < n:
                entry_i = i + 1
                entry_price = open_[i + 1]
                in_pos = True
                pr = 0.0

        equity *= (1 + pr)
        peak_eq = max(peak_eq, equity)
        mdd = max(mdd, (peak_eq - equity) / peak_eq)
        eq_curve.append(equity)
        ret_list.append(pr)

    years = n / 252
    cagr = float((equity / 100) ** (1 / years) - 1) if years > 0 else 0
    win_rate = (sum(1 for t in trades if t > 0) / len(trades) * 100) if trades else None

    return {
        "cagr": round(cagr * 100, 1),
        "mdd": round(mdd * 100, 1),
        "trades": len(trades),
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "final_equity": round(equity, 1),
    }


def main():
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    period = sys.argv[2] if len(sys.argv) > 2 else "6y"

    tickers = list(bot.POPULAR_STOCKS.keys())
    random.seed(42)
    sample = random.sample(tickers, min(n_sample, len(tickers)))

    results_a, results_b = [], []
    for t in sample:
        try:
            ra = bot.backtest_stock(t, period=period)
        except Exception as e:
            ra = None
            print(f"  [A] {t} 오류: {e}")
        try:
            rb = backtest_screen_b(t, period=period)
        except Exception as e:
            rb = None
            print(f"  [B] {t} 오류: {e}")

        print(f"{t:12s}  A) {('CAGR %5.1f%%  MDD %5.1f%%' % (ra['cagr'], ra['mdd'])) if ra else '데이터 없음'}"
              f"   |   B) {('CAGR %5.1f%%  MDD %5.1f%%  거래수 %d  승률 %s' % (rb['cagr'], rb['mdd'], rb['trades'], rb['win_rate'])) if rb else '스크리닝 통과 못함/데이터 없음'}")

        if ra:
            results_a.append(ra["cagr"])
        if rb:
            results_b.append(rb["cagr"])

    def summary(label, arr):
        if not arr:
            print(f"\n{label}: 결과 없음")
            return
        a = np.array(arr)
        print(f"\n{label} (n={len(a)}): 평균CAGR {a.mean():.1f}%  중앙값 {np.median(a):.1f}%  "
              f"표준편차 {a.std():.1f}%  양수비율 {(a>0).mean()*100:.0f}%")

    print("\n" + "=" * 70)
    summary("A) 현재 투자법(기술적 점수 BUY/SELL 시그널)", results_a)
    summary("B) 신고가근접+거래량5배+실적우상향 스크리닝", results_b)
    print("=" * 70)


if __name__ == "__main__":
    main()
