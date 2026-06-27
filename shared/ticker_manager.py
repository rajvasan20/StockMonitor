"""Fetch and maintain the list of NSE-listed equity tickers."""

import os
import time
import json
import requests
import pandas as pd
from config import DATA_DIR, NSE_EQUITY_CSV_URL, TICKER_CACHE_MAX_AGE_DAYS
from shared.utils import logger

TICKERS_CSV = os.path.join(DATA_DIR, "tickers.csv")
NIFTY500_CSV = os.path.join(DATA_DIR, "nifty500.csv")
LAST_RUN_FILE = os.path.join(DATA_DIR, "last_run.json")
FAILURES_FILE = os.path.join(DATA_DIR, "failures.json")


def fetch_nse_tickers():
    """Download the NSE equity list and cache it locally."""
    logger.info("Downloading NSE equity list...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(NSE_EQUITY_CSV_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        raw_path = os.path.join(DATA_DIR, "EQUITY_L_raw.csv")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(resp.text)
        df = pd.read_csv(raw_path)
        df.columns = [c.strip() for c in df.columns]
        if " SERIES" in df.columns:
            df = df[df[" SERIES"].str.strip() == "EQ"]
        elif "SERIES" in df.columns:
            df = df[df["SERIES"].str.strip() == "EQ"]
        symbol_col = "SYMBOL" if "SYMBOL" in df.columns else df.columns[0]
        df["TICKER"] = df[symbol_col].str.strip()
        df = df[["TICKER"]].drop_duplicates().sort_values("TICKER").reset_index(drop=True)
        df.to_csv(TICKERS_CSV, index=False)
        logger.info(f"Cached {len(df)} EQ tickers to {TICKERS_CSV}")
        return df
    except Exception as e:
        logger.error(f"Failed to download NSE tickers: {e}")
        return None


def load_cached_tickers():
    """Load tickers from local cache."""
    if not os.path.exists(TICKERS_CSV):
        return None
    df = pd.read_csv(TICKERS_CSV)
    return df


def is_cache_stale():
    """Check if cached ticker list is too old."""
    if not os.path.exists(TICKERS_CSV):
        return True
    age_days = (time.time() - os.path.getmtime(TICKERS_CSV)) / 86400
    return age_days > TICKER_CACHE_MAX_AGE_DAYS


def get_ticker_list():
    """Return sorted list of ticker symbols. Refreshes cache if stale."""
    if is_cache_stale():
        df = fetch_nse_tickers()
        if df is None:
            df = load_cached_tickers()
    else:
        df = load_cached_tickers()

    if df is None or df.empty:
        logger.error("No tickers available!")
        return []

    return df["TICKER"].tolist()


def get_nifty500_list():
    """Return sorted list of Nifty 500 ticker symbols."""
    if not os.path.exists(NIFTY500_CSV):
        logger.error(f"Nifty 500 list not found: {NIFTY500_CSV}")
        return []
    df = pd.read_csv(NIFTY500_CSV)
    col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    tickers = df[col].str.strip().dropna().drop_duplicates().sort_values().tolist()
    logger.info(f"Loaded {len(tickers)} Nifty 500 tickers")
    return tickers


# --- State tracking ---

def load_last_run():
    """Load last-run timestamps per ticker."""
    if not os.path.exists(LAST_RUN_FILE):
        return {}
    with open(LAST_RUN_FILE, "r") as f:
        return json.load(f)


def save_last_run(state):
    """Save last-run state."""
    with open(LAST_RUN_FILE, "w") as f:
        json.dump(state, f)


def mark_completed(ticker, state):
    """Mark a ticker as completed in current cycle."""
    state[ticker] = time.time()
    save_last_run(state)


def should_skip(ticker, state, max_age_hours=24):
    """Skip if already processed within max_age_hours."""
    ts = state.get(ticker)
    if ts is None:
        return False
    age_hours = (time.time() - ts) / 3600
    return age_hours < max_age_hours


def load_failures():
    """Load set of tickers that returned 404 (not on Screener)."""
    if not os.path.exists(FAILURES_FILE):
        return set()
    with open(FAILURES_FILE, "r") as f:
        return set(json.load(f))


def save_failure(ticker, failures):
    """Add a ticker to the failure set."""
    failures.add(ticker)
    with open(FAILURES_FILE, "w") as f:
        json.dump(list(failures), f)
