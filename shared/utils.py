"""Shared utilities: logging, math helpers, formatting, daily caching."""

import logging
import os
import re
import json
import math
import numpy as np
from datetime import datetime
from logging.handlers import RotatingFileHandler
from config import LOGS_DIR

_DAILY_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "data", "cache", "daily")


def setup_logging():
    """Configure rotating file + console logging."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger("stock_monitor")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # File handler
        fh = RotatingFileHandler(
            os.path.join(LOGS_DIR, "monitor.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
        logger.addHandler(ch)

    return logger


logger = setup_logging()


def safe_float(value):
    """Convert a string like '1,234.56' or '12.3%' to float. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in ("-", "", "\u2014", "N/A", "NA"):
        return None
    s = s.replace(",", "").replace("%", "").replace("\u20b9", "").replace("Cr.", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def cagr(start, end, years):
    """Compound Annual Growth Rate. Returns None if invalid."""
    if start is None or end is None or years is None or years <= 0:
        return None
    if start <= 0 or end <= 0:
        return None
    try:
        return (end / start) ** (1 / years) - 1
    except (ZeroDivisionError, ValueError):
        return None


def growth_rate(values):
    """Calculate CAGR from a list of annual values (oldest first)."""
    clean = [v for v in values if v is not None and v > 0]
    if len(clean) < 2:
        return None
    return cagr(clean[0], clean[-1], len(clean) - 1)


def median(values):
    """Median of a list, ignoring None."""
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return None
    clean.sort()
    n = len(clean)
    if n % 2 == 1:
        return clean[n // 2]
    return (clean[n // 2 - 1] + clean[n // 2]) / 2


def mean(values):
    """Mean of a list, ignoring None."""
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def trim_outliers(values, sigma=2):
    """Remove values beyond N standard deviations from mean."""
    clean = [v for v in values if v is not None and not math.isnan(v) and v > 0]
    if len(clean) < 3:
        return clean
    m = np.mean(clean)
    s = np.std(clean)
    if s == 0:
        return clean
    return [v for v in clean if abs(v - m) <= sigma * s]


def format_inr(value):
    """Format a number as INR string with commas."""
    if value is None:
        return "N/A"
    if abs(value) >= 1e7:
        return f"\u20b9{value / 1e7:,.2f} Cr"
    if abs(value) >= 1e5:
        return f"\u20b9{value / 1e5:,.2f} L"
    return f"\u20b9{value:,.2f}"


def format_pct(value):
    """Format as percentage string."""
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


# ═══════════════════════════════════════════════════════════════
# Daily TTL Cache
# ═══════════════════════════════════════════════════════════════

def daily_cache_get(key: str):
    """Load today's cached JSON for a given key. Returns None if missing/stale."""
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(_DAILY_CACHE_DIR, f"{key}_{today}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Cache hit: {key} (today)")
        return data
    except Exception:
        return None


def daily_cache_set(key: str, data) -> None:
    """Save data as today's JSON cache for a given key."""
    os.makedirs(_DAILY_CACHE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(_DAILY_CACHE_DIR, f"{key}_{today}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Cache write failed for {key}: {e}")


def purge_daily_cache(max_age_days: int = 7) -> int:
    """Delete daily cache files older than max_age_days."""
    if not os.path.exists(_DAILY_CACHE_DIR):
        return 0
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = 0
    for fname in os.listdir(_DAILY_CACHE_DIR):
        fpath = os.path.join(_DAILY_CACHE_DIR, fname)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)
                deleted += 1
        except OSError:
            pass
    return deleted
