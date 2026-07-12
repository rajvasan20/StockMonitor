"""
Price Fetcher — Fetch latest share prices for analysis tracker stocks.

Fetches current market prices from Yahoo Finance (NSE) for every ticker
in the analysis tracker and stores them as a JSON file that the tracker
HTML reads to show live prices and highlight accumulation zones.

Usage:
    python run.py prices              # Fetch all tracker tickers
    python run.py prices --ticker TCS # Fetch single ticker
"""

import os
import json
import re
import time
from datetime import datetime
from typing import Optional

import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.utils import logger

# Output path for price memory
PRICE_MEMORY_DIR = os.path.join(PROJECT_ROOT, "data", "price_memory")
PRICE_FILE = os.path.join(PRICE_MEMORY_DIR, "latest_prices.json")
# Also write to output/ so the HTML can load it via relative path
OUTPUT_PRICE_FILE = os.path.join(PROJECT_ROOT, "output", "latest_prices.json")


# All tickers tracked in analysis_tracker.html
TRACKER_TICKERS = [
    "ETERNAL", "TECHM", "SBILIFE", "BEL", "JSWSTEEL", "ITC", "BAJAJFINSV",
    "BAJFINANCE", "APOLLO", "EPACK", "CEMPRO", "MARUTI", "ICICIBANK",
    "HDFCBANK", "BAJAJ-AUTO", "TCS", "INFY", "HCLTECH", "ACE", "AGIIL",
    "AHCL", "ALKYLAMINE", "ALLDIGI", "BLS", "CAMS", "CONTROLPR",
    "DRCSYSTEMS", "ECOSMOBLTY", "GANDHITUBE", "GRAUWEIL", "GRWRHITECH",
    "JLHL", "JYOTHYLAB", "JYOTIRESINS", "KFINTECH", "KOVAI", "KPRMILL",
    "MANAPPURAM", "SOUTHBANK", "MANKIND", "OSWALPUMPS", "SHANTIGEAR",
    "STYL", "SUNPHARMA", "TANFAC", "TRITURBINE", "VSTIND", "WAAREEENER",
    "KPITTECH", "APOLLOHOSP", "PERSISTENT", "TATATECH", "INDIAMART",
    "CUMMINSIND", "IEX", "EICHERMOT", "LALPATHLAB", "ECLERX", "CDSL",
    "TRAVELFOOD", "SOLARINDS", "MCX", "PIIND", "JBCHEPHARM", "MEDANTA",
    "LTM", "INOXINDIA", "CRISIL", "VIJAYA", "GRINDWELL", "SUPREMEIND",
    "NATIONALUM", "TATAELXSI", "RAINBOW", "ZYDUSLIFE", "NH", "PIDILITIND",
    "COFORGE", "INDUSTOWER", "GPIL", "NCC", "ABB", "CGPOWER", "RRKABEL",
    "BLUESTARCO", "KEI", "RAILTEL", "THERMAX", "AMARAJA", "LT",
    "TATAPOWER", "KEC", "RELIANCE", "NTPC", "POWERGRID", "SIEMENS",
    "POLYCAB", "KIRLOSENG", "HAVELLS", "FINCABLES", "VOLTAS", "EXIDEIND",
    "BHARTIARTL", "ADANIENT", "STLTECH", "HFCL", "TEJASNET", "AEGISLOG",
    "AVALON", "HINDALCO", "ONGC", "TITAN",
]


# Yahoo Finance symbol overrides for tickers that differ from NSE codes
_YAHOO_OVERRIDES = {
    "AMARAJA": "ARE&M",  # Amara Raja Energy & Mobility
}


def _nse_symbol(ticker: str) -> str:
    """Convert NSE ticker to Yahoo Finance symbol."""
    t = ticker.strip().upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    t = _YAHOO_OVERRIDES.get(t, t)
    return f"{t}.NS"


def fetch_latest_prices(tickers: Optional[list] = None, batch_size: int = 20) -> dict:
    """Fetch latest prices for all tickers using yfinance batch download.

    Returns dict: {ticker: {price, change_pct, high_52w, low_52w, volume, timestamp}}
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return {}

    if tickers is None:
        tickers = TRACKER_TICKERS

    symbols = [_nse_symbol(t) for t in tickers]
    # Map Yahoo symbol back to original ticker name
    ticker_map = {_nse_symbol(t): t for t in tickers}

    prices = {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Batch download in chunks to avoid timeouts
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        batch_str = " ".join(batch)
        logger.info(f"Fetching batch {i // batch_size + 1}: {len(batch)} tickers")

        try:
            data = yf.download(batch_str, period="5d", progress=False, auto_adjust=True)

            if data is None or data.empty:
                logger.warning(f"Batch {i // batch_size + 1}: No data returned")
                continue

            for symbol in batch:
                orig_ticker = ticker_map.get(symbol, symbol.replace(".NS", ""))
                try:
                    if isinstance(data.columns, type(data.columns)) and hasattr(data.columns, 'nlevels') and data.columns.nlevels > 1:
                        # MultiIndex columns (multiple tickers)
                        if symbol in data["Close"].columns:
                            close_series = data["Close"][symbol].dropna()
                        else:
                            logger.warning(f"{orig_ticker}: No data in batch response")
                            continue
                    else:
                        # Single ticker — flat columns
                        close_series = data["Close"].dropna()

                    if close_series.empty:
                        logger.warning(f"{orig_ticker}: Empty close series")
                        continue

                    latest_price = float(close_series.iloc[-1])
                    prev_price = float(close_series.iloc[-2]) if len(close_series) > 1 else latest_price
                    change_pct = round(((latest_price - prev_price) / prev_price) * 100, 2) if prev_price else 0

                    prices[orig_ticker] = {
                        "price": round(latest_price, 2),
                        "change_pct": change_pct,
                        "prev_close": round(prev_price, 2),
                        "timestamp": now,
                        "trade_date": str(close_series.index[-1].date()),
                    }

                except Exception as e:
                    logger.warning(f"{orig_ticker}: Failed to extract price — {e}")

        except Exception as e:
            logger.error(f"Batch {i // batch_size + 1} failed: {e}")

        # Rate limit between batches
        if i + batch_size < len(symbols):
            time.sleep(1)

    logger.info(f"Fetched prices for {len(prices)}/{len(tickers)} tickers")
    return prices


def save_prices(prices: dict) -> str:
    """Save prices to JSON files (data/ and output/)."""
    os.makedirs(PRICE_MEMORY_DIR, exist_ok=True)

    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(prices),
        "prices": prices,
    }

    # Write to both locations
    for path in [PRICE_FILE, OUTPUT_PRICE_FILE]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info(f"Prices saved: {PRICE_FILE}")
    logger.info(f"Prices saved: {OUTPUT_PRICE_FILE}")
    return PRICE_FILE


def load_prices() -> dict:
    """Load latest prices from JSON."""
    if os.path.exists(PRICE_FILE):
        with open(PRICE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def run(ticker: Optional[str] = None):
    """Main entry point for CLI."""
    logger.info("=" * 60)
    logger.info("Price Fetcher — Analysis Tracker")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    tickers = None
    if ticker:
        tickers = [t.strip().upper() for t in ticker.split(",")]

    prices = fetch_latest_prices(tickers=tickers)

    if not prices:
        logger.error("No prices fetched. Check network/yfinance.")
        return

    # Merge with existing prices if fetching subset
    if ticker and os.path.exists(PRICE_FILE):
        existing = load_prices()
        existing_prices = existing.get("prices", {})
        existing_prices.update(prices)
        prices = existing_prices

    path = save_prices(prices)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  PRICE UPDATE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")
    print(f"{'Ticker':<14} {'Price':>10} {'Chg%':>8} {'Date':<12}")
    print("-" * 50)
    for t in sorted(prices.keys()):
        p = prices[t]
        chg = p.get("change_pct", 0)
        chg_str = f"{chg:+.2f}%" if chg else "--"
        print(f"{t:<14} Rs{p['price']:>9,.2f} {chg_str:>8} {p.get('trade_date', '--')}")

    print(f"\n  Total: {len(prices)} tickers")
    print(f"  Saved: {path}")


if __name__ == "__main__":
    run()
