import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def download_crypto_data():
    # 1. 수집할 자산 티커 설정 (BTC-USD, ETH-USD)
    tickers = ["BTC-USD", "ETH-USD"]
    
    # 2. 날짜 설정 (오늘부터 5년 전까지)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')
    
    print(f"데이터 수집 시작: {start_date} ~ {end_date}")

    # 3. 데이터 다운로드
    # group_by='ticker'를 사용하면 각 코인별로 데이터를 묶어서 관리하기 편합니다.
    data = yf.download(tickers, start=start_date, end=end_date, group_by='ticker')

    # 4. 데이터 저장 (CSV 파일)
    # BTC와 ETH 데이터를 각각 분리해서 저장하는 것이 분석하기에 더 깔끔합니다.
    for ticker in tickers:
        ticker_data = data[ticker]
        filename = f"{ticker.replace('-USD', '')}_5yr_data.csv"
        ticker_data.to_csv(filename)
        print(f"저장 완료: {filename}")

    return data

if __name__ == "__main__":
    df = download_crypto_data()
    
    # 5. 수집된 데이터 샘플 확인 (BTC 기준 상단 5줄)
    print("\n[BTC 데이터 샘플]")
    print(df["BTC-USD"].head())