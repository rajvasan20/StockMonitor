"""Download Screener.in data for all NSE tickers not yet in ticker_excels."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from universe_monitor.engine import run_cycle

# Find missing tickers
tickers_csv = os.path.join("data", "tickers.csv")
excels_dir = os.path.join("data", "ticker_excels")

df = pd.read_csv(tickers_csv)
all_tickers = sorted(df["TICKER"].str.strip().tolist())
existing = set(f.replace(".xlsx", "") for f in os.listdir(excels_dir) if f.endswith(".xlsx"))
missing = [t for t in all_tickers if t not in existing]

print(f"Total NSE tickers: {len(all_tickers)}")
print(f"Already downloaded: {len(existing)}")
print(f"Missing: {len(missing)}")
print(f"\nStarting download of {len(missing)} tickers...")

run_cycle(tickers=missing, skip_recent=False)
