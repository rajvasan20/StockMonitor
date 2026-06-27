"""Price data fetcher using yfinance for Indian equities.

NSE tickers use .NS suffix on Yahoo Finance (e.g., TCS.NS, RELIANCE.NS).
Fetches daily OHLCV data for technical indicator calculation.

Caching: Daily parquet files stored in data/cache/<TICKER>_YYYY-MM-DD.parquet.
Cache hit = instant load from disk. Cache miss = yfinance fetch + save.
Files older than 7 days are auto-purged on each run.
"""

import os
import time
import random
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from shared.utils import logger

# yfinance imported lazily to avoid hard dependency at module load
_yf = None

# Cache directory
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache")


def _get_yf():
    global _yf
    if _yf is None:
        try:
            import yfinance as yf
            _yf = yf
        except ImportError:
            raise ImportError(
                "yfinance is required for technical analysis. "
                "Install it: pip install yfinance"
            )
    return _yf


def _nse_symbol(ticker: str) -> str:
    """Convert NSE ticker to Yahoo Finance symbol."""
    t = ticker.strip().upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    return f"{t}.NS"


def _cache_path(ticker: str, date_str: str) -> str:
    """Return path for a ticker's daily cache file."""
    safe_ticker = ticker.strip().upper().replace("&", "_AND_")
    return os.path.join(_CACHE_DIR, f"{safe_ticker}_{date_str}.parquet")


def _find_latest_cache(ticker: str) -> Optional[str]:
    """Find the most recent cache file for a ticker, regardless of date."""
    if not os.path.exists(_CACHE_DIR):
        return None
    safe_ticker = ticker.strip().upper().replace("&", "_AND_")
    prefix = f"{safe_ticker}_"
    candidates = [f for f in os.listdir(_CACHE_DIR)
                  if f.startswith(prefix) and f.endswith(".parquet")]
    if not candidates:
        return None
    # Sort by date in filename (YYYY-MM-DD) descending
    candidates.sort(reverse=True)
    return os.path.join(_CACHE_DIR, candidates[0])


def _read_cache(ticker: str, days: int) -> Optional[pd.DataFrame]:
    """Try to load today's cached data for a ticker."""
    today = datetime.now().strftime("%Y-%m-%d")
    path = _cache_path(ticker, today)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        if len(df) < 20:
            return None
        # Verify cache has enough history for requested days
        if len(df) < min(days * 0.6, 200):  # rough check — 60% of calendar days
            return None
        logger.info(f"{ticker}: Cache hit ({len(df)} days from {path})")
        return df
    except Exception as e:
        logger.warning(f"{ticker}: Cache read failed: {e}")
        return None


def _write_cache(ticker: str, df: pd.DataFrame) -> None:
    """Save a ticker's OHLCV data to today's cache file."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = _cache_path(ticker, today)
    try:
        df.to_parquet(path)
    except Exception as e:
        logger.warning(f"{ticker}: Cache write failed: {e}")


def purge_old_cache(max_age_days: int = 7) -> int:
    """Delete cache files older than max_age_days. Returns count deleted."""
    if not os.path.exists(_CACHE_DIR):
        return 0
    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = 0
    for fname in os.listdir(_CACHE_DIR):
        if not fname.endswith(".parquet"):
            continue
        fpath = os.path.join(_CACHE_DIR, fname)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)
                deleted += 1
        except OSError:
            pass
    if deleted:
        logger.info(f"Cache purge: removed {deleted} files older than {max_age_days} days")
    return deleted


def fetch_daily_ohlcv(ticker: str, days: int = 365,
                       end_date: Optional[datetime] = None,
                       skip_cache: bool = False) -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV data for a ticker.

    Returns DataFrame with columns: Open, High, Low, Close, Volume
    Index is DatetimeIndex. Returns None on failure.

    Uses daily file cache: data/cache/<TICKER>_YYYY-MM-DD.parquet.
    Pass skip_cache=True to force a fresh fetch.
    """
    # Try cache first (only for default end_date = today)
    if not skip_cache and end_date is None:
        cached = _read_cache(ticker, days)
        if cached is not None:
            return cached

    yf = _get_yf()
    symbol = _nse_symbol(ticker)

    if end_date is None:
        end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # ── Incremental fetch: try to extend a recent cache ─────────
    if not skip_cache:
        latest_path = _find_latest_cache(ticker)
        if latest_path:
            try:
                old_df = pd.read_parquet(latest_path)
                if len(old_df) >= 20:
                    last_cached_date = old_df.index[-1]
                    # Fetch only from day after last cached date
                    inc_start = last_cached_date + timedelta(days=1)
                    if inc_start.date() < end_date.date():
                        new_data = yf.download(
                            symbol,
                            start=inc_start.strftime("%Y-%m-%d"),
                            end=end_date.strftime("%Y-%m-%d"),
                            progress=False,
                            auto_adjust=True,
                        )
                        if new_data is not None and not new_data.empty:
                            if isinstance(new_data.columns, pd.MultiIndex):
                                new_data.columns = new_data.columns.get_level_values(0)
                            new_data = new_data[["Open", "High", "Low", "Close", "Volume"]].dropna()

                        if new_data is not None and not new_data.empty:
                            combined = pd.concat([old_df, new_data])
                            combined = combined[~combined.index.duplicated(keep='last')]
                            combined.sort_index(inplace=True)
                            # Trim to requested window
                            combined = combined[combined.index >= pd.Timestamp(start_date)]
                            if len(combined) >= 20:
                                logger.info(f"{ticker}: Incremental +{len(new_data)} days "
                                            f"(total {len(combined)}, from cache {os.path.basename(latest_path)})")
                                _write_cache(ticker, combined)
                                return combined
                        else:
                            # No new data — market closed or weekend; reuse old cache
                            trimmed = old_df[old_df.index >= pd.Timestamp(start_date)]
                            if len(trimmed) >= 20:
                                logger.info(f"{ticker}: Cache reuse ({len(trimmed)} days, "
                                            f"no new data since {last_cached_date.strftime('%Y-%m-%d')})")
                                _write_cache(ticker, trimmed)
                                return trimmed
            except Exception as e:
                logger.debug(f"{ticker}: Incremental cache failed ({e}), falling back to full fetch")

    # ── Full fetch (fallback) ───────────────────────────────────
    try:
        data = yf.download(
            symbol,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )

        if data is None or data.empty:
            logger.warning(f"{ticker}: No price data from Yahoo Finance")
            return None

        # yfinance may return MultiIndex columns for single ticker
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(set(data.columns)):
            logger.warning(f"{ticker}: Incomplete OHLCV columns: {data.columns.tolist()}")
            return None

        data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

        if len(data) < 20:
            logger.warning(f"{ticker}: Only {len(data)} trading days — need at least 20")
            return None

        logger.info(f"{ticker}: Full fetch {len(data)} days of price data")

        # Write to cache (only for default end_date = today)
        if not skip_cache:
            _write_cache(ticker, data)

        return data

    except Exception as e:
        logger.error(f"{ticker}: Failed to fetch price data: {e}")
        return None


def fetch_multiple(tickers: list, days: int = 365,
                    delay: float = 0.5) -> dict:
    """Fetch OHLCV for multiple tickers with rate limiting.

    Returns dict of {ticker: DataFrame}.
    """
    results = {}
    for i, ticker in enumerate(tickers):
        df = fetch_daily_ohlcv(ticker, days=days)
        if df is not None:
            results[ticker] = df
        if i < len(tickers) - 1:
            time.sleep(delay + random.uniform(0, 0.3))
    return results
