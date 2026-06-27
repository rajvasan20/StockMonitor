"""Flow Tracker — money flow traceability dashboard for all Nifty 100 stocks.

Traces institutional money flow from market-level FII/DII aggregates down to
stock-level delivery data, bulk/block deals, and flow indicators.
Answers: "How much money is stashed in this stock, and where did it come from?"

Data layers:
1. FII/DII aggregate flows (market context)
2. Stock delivery data from NSE bhavcopy (delivery_qty x price = institutional-grade value)
3. Bulk/block deals (named institutional transactions)
4. Flow indicators (MFI, CMF, OBV from OHLCV)

Time filters: Day / Week / Month (all data loaded, JS toggles view)
Stock selector: dropdown to pick any Nifty 100 stock
"""

import os
import io
import json
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Set

import requests
import pandas as pd
import numpy as np

from technicals.indicators import compute_all_indicators
from technicals.data_fetcher import fetch_daily_ohlcv
from short_term.nse_events import (
    fetch_bulk_deals, fetch_block_deals, BulkBlockDeal,
)
from dashboard.money_flow import fetch_fii_dii_flows
from dashboard.nifty100 import NIFTY_100
from dashboard.sectors import get_sector_industry
from shared.utils import logger

IST = timezone(timedelta(hours=5, minutes=30))

BHAVCOPY_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"


# ═══════════════════════════════════════════════════════════════
# Data Assembly
# ═══════════════════════════════════════════════════════════════

def _safe(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


_BHAVCOPY_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "cache", "bhavcopy"
)


def _bhavcopy_cache_path(date_key: str) -> str:
    return os.path.join(_BHAVCOPY_CACHE_DIR, f"{date_key}.json")


def _load_bhavcopy_cache(date_key: str) -> Optional[Dict[str, dict]]:
    """Load cached bhavcopy data for a single date. Returns {ticker: row_dict} or None."""
    path = _bhavcopy_cache_path(date_key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _save_bhavcopy_cache(date_key: str, data: Dict[str, dict]) -> None:
    """Save a single day's bhavcopy data. data = {ticker: row_dict}."""
    os.makedirs(_BHAVCOPY_CACHE_DIR, exist_ok=True)
    path = _bhavcopy_cache_path(date_key)
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _parse_bhavcopy_row(r) -> Optional[dict]:
    """Parse a single bhavcopy row into our standard dict."""
    try:
        close = float(r.get("CLOSE_PRICE", 0))
        prev_cl = float(r.get("PREV_CLOSE", 0))
        volume = int(float(r.get("TTL_TRD_QNTY", 0)))
        dq_raw = str(r.get("DELIV_QTY", "0")).strip()
        delivery_qty = int(float(dq_raw)) if dq_raw and dq_raw != "-" else 0
        dp_raw = str(r.get("DELIV_PER", "0")).strip()
        delivery_pct = float(dp_raw) if dp_raw and dp_raw != "-" else 0.0
        turnover_lacs = float(r.get("TURNOVER_LACS", 0))
        change_pct = ((close / prev_cl) - 1) * 100 if prev_cl > 0 else 0
        delivered_value_cr = (delivery_qty * close) / 1e7 if delivery_qty > 0 else 0
        turnover_cr = turnover_lacs / 100
        return {
            "close": round(close, 2),
            "open": round(float(r.get("OPEN_PRICE", 0)), 2),
            "high": round(float(r.get("HIGH_PRICE", 0)), 2),
            "low": round(float(r.get("LOW_PRICE", 0)), 2),
            "change_pct": round(change_pct, 2),
            "volume": volume,
            "delivery_qty": delivery_qty,
            "delivery_pct": round(delivery_pct, 1),
            "delivered_value_cr": round(delivered_value_cr, 2),
            "turnover_cr": round(turnover_cr, 2),
        }
    except (ValueError, TypeError):
        return None


def _fetch_all_bhavcopy(tickers_set: Set[str], days: int = 30) -> Dict[str, List[dict]]:
    """Fetch bhavcopy CSVs and extract delivery data for ALL tickers at once.

    Returns {ticker: [daily_row_dicts]} sorted by date ascending per ticker.
    Uses per-day JSON cache — only fetches days not already cached.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
    })

    result: Dict[str, List[dict]] = {t: [] for t in tickers_set}

    today = datetime.now()
    fetched_days = 0
    fetched_from_net = 0
    fetched_from_cache = 0
    attempts = 0
    max_attempts = days + 20

    while fetched_days < days and attempts < max_attempts:
        dt = today - timedelta(days=attempts + 1)
        attempts += 1

        if dt.weekday() >= 5:
            continue

        date_key = dt.strftime("%Y-%m-%d")

        # ── Try cache first ─────────────────────────────────────
        cached = _load_bhavcopy_cache(date_key)
        if cached is not None:
            matched = 0
            for ticker in tickers_set:
                if ticker in cached:
                    row = cached[ticker]
                    row["date"] = date_key
                    result[ticker].append(row)
                    matched += 1
            fetched_days += 1
            fetched_from_cache += 1
            continue

        # ── Fetch from NSE ──────────────────────────────────────
        date_str = dt.strftime("%d%m%Y")
        url = BHAVCOPY_URL.format(date_str)

        try:
            resp = session.get(url, timeout=12)
            if resp.status_code != 200 or len(resp.text) < 200:
                continue

            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [c.strip() for c in df.columns]

            if "SERIES" in df.columns:
                df = df[df["SERIES"].str.strip() == "EQ"]

            df["SYMBOL"] = df["SYMBOL"].str.strip()

            # Parse ALL EQ rows for cache (not just our tickers)
            day_cache: Dict[str, dict] = {}
            for _, r in df.iterrows():
                sym = r["SYMBOL"]
                parsed = _parse_bhavcopy_row(r)
                if parsed:
                    day_cache[sym] = parsed

            # Save full day to cache
            _save_bhavcopy_cache(date_key, day_cache)

            # Extract our tickers
            matched = 0
            for ticker in tickers_set:
                if ticker in day_cache:
                    row = dict(day_cache[ticker])
                    row["date"] = date_key
                    result[ticker].append(row)
                    matched += 1

            fetched_days += 1
            fetched_from_net += 1
            logger.info(f"  Bhavcopy {date_key}: {matched} tickers (fetched from NSE)")

        except Exception as e:
            logger.debug(f"Bhavcopy {date_key}: {e}")
            continue

        if fetched_from_net % 5 == 0 and fetched_from_net > 0:
            time.sleep(0.3)

    # Sort each ticker's data by date ascending
    for t in result:
        result[t].sort(key=lambda x: x["date"])

    total_rows = sum(len(v) for v in result.values())
    tickers_with_data = sum(1 for v in result.values() if v)
    logger.info(f"Bhavcopy: {fetched_days} days ({fetched_from_cache} cached, "
                f"{fetched_from_net} fetched), {tickers_with_data} tickers, {total_rows} rows")
    return result


def _compute_flow_indicators(df: pd.DataFrame) -> dict:
    """Extract MFI, CMF, OBV and other flow indicators from computed OHLCV."""
    df = compute_all_indicators(df)
    last = df.iloc[-1]
    indicators = {}

    # MFI
    mfi = _safe(last.get("MFI"))
    indicators["mfi"] = mfi
    if mfi is not None:
        if mfi >= 80: indicators["mfi_signal"] = "Strong Inflow"
        elif mfi >= 60: indicators["mfi_signal"] = "Inflow"
        elif mfi <= 20: indicators["mfi_signal"] = "Strong Outflow"
        elif mfi <= 40: indicators["mfi_signal"] = "Outflow"
        else: indicators["mfi_signal"] = "Neutral"
    else:
        indicators["mfi_signal"] = "N/A"

    # CMF
    cmf = _safe(last.get("CMF"))
    indicators["cmf"] = cmf
    if cmf is not None:
        if cmf >= 0.15: indicators["cmf_signal"] = "Strong Accumulation"
        elif cmf >= 0.05: indicators["cmf_signal"] = "Accumulation"
        elif cmf <= -0.15: indicators["cmf_signal"] = "Strong Distribution"
        elif cmf <= -0.05: indicators["cmf_signal"] = "Distribution"
        else: indicators["cmf_signal"] = "Neutral"
    else:
        indicators["cmf_signal"] = "N/A"

    # OBV
    if "OBV" in df.columns and "OBV_SMA_20" in df.columns:
        obv = _safe(last.get("OBV"))
        obv_sma = _safe(last.get("OBV_SMA_20"))
        indicators["obv"] = obv
        indicators["obv_sma"] = obv_sma
        if obv is not None and obv_sma is not None and obv_sma != 0:
            if obv > obv_sma * 1.02: indicators["obv_signal"] = "Rising (Accumulation)"
            elif obv < obv_sma * 0.98: indicators["obv_signal"] = "Falling (Distribution)"
            else: indicators["obv_signal"] = "Flat"
        else:
            indicators["obv_signal"] = "N/A"

        if len(df) >= 20:
            price_20d = (df["Close"].iloc[-1] / df["Close"].iloc[-20] - 1) * 100
            obv_start = df["OBV"].iloc[-20]
            obv_end = df["OBV"].iloc[-1]
            obv_20d = (obv_end / obv_start - 1) * 100 if obv_start > 0 else 0
            if price_20d < -2 and obv_20d > 5:
                indicators["obv_divergence"] = "Bullish (price down, OBV up)"
            elif price_20d > 2 and obv_20d < -5:
                indicators["obv_divergence"] = "Bearish (price up, OBV down)"
            else:
                indicators["obv_divergence"] = "None"
        else:
            indicators["obv_divergence"] = "N/A"
    else:
        indicators["obv_signal"] = "N/A"
        indicators["obv_divergence"] = "N/A"

    indicators["vol_ratio"] = _safe(last.get("Volume_Ratio"))

    if len(df) >= 40:
        vol_20d = df["Volume"].iloc[-20:].mean()
        vol_prev_20d = df["Volume"].iloc[-40:-20].mean()
        indicators["vol_trend_20d"] = round((vol_20d / vol_prev_20d - 1) * 100, 1) if vol_prev_20d > 0 else None
    else:
        indicators["vol_trend_20d"] = None

    if len(df) >= 20:
        price_range = (df["High"].iloc[-20:].max() - df["Low"].iloc[-20:].min()) / df["Close"].iloc[-20:].mean() * 100
        vt = indicators.get("vol_trend_20d")
        if vt is not None and vt > 20 and price_range < 10:
            indicators["accumulation_pattern"] = "Quiet Accumulation"
        elif vt is not None and vt < -20 and price_range < 10:
            indicators["accumulation_pattern"] = "Distribution"
        else:
            indicators["accumulation_pattern"] = "None detected"
    else:
        indicators["accumulation_pattern"] = "N/A"

    return indicators


def _aggregate_fii_dii(flows: Optional[List[dict]]) -> dict:
    """Aggregate FII/DII flows into a structured dict keyed by date."""
    result = {"dates": {}, "summary": {"fii_net_total": 0, "dii_net_total": 0}}
    if not flows:
        return result

    for entry in flows:
        date_str = entry.get("date", "")
        cat = entry.get("category", "")
        net = entry.get("net", 0)

        if date_str not in result["dates"]:
            result["dates"][date_str] = {
                "fii_net": 0, "dii_net": 0,
                "fii_buy": 0, "fii_sell": 0,
                "dii_buy": 0, "dii_sell": 0,
            }

        if "FII" in cat.upper() or "FPI" in cat.upper():
            result["dates"][date_str]["fii_net"] = net
            result["dates"][date_str]["fii_buy"] = entry.get("buy", 0)
            result["dates"][date_str]["fii_sell"] = entry.get("sell", 0)
            result["summary"]["fii_net_total"] += net
        elif "DII" in cat.upper():
            result["dates"][date_str]["dii_net"] = net
            result["dates"][date_str]["dii_buy"] = entry.get("buy", 0)
            result["dates"][date_str]["dii_sell"] = entry.get("sell", 0)
            result["summary"]["dii_net_total"] += net

    return result


def _group_deals_by_ticker(
    bulk_deals: List[BulkBlockDeal],
    block_deals: List[BulkBlockDeal],
) -> Dict[str, List[dict]]:
    """Group all deals by ticker symbol."""
    grouped: Dict[str, List[dict]] = {}
    for d in bulk_deals + block_deals:
        ticker = d.ticker.upper()
        if ticker not in grouped:
            grouped[ticker] = []
        grouped[ticker].append({
            "date": d.date,
            "client": d.client,
            "deal_type": d.deal_type,
            "quantity": d.quantity,
            "price": round(d.price, 2),
            "value_cr": round(d.quantity * d.price / 1e7, 2),
            "source": d.source,
        })
    return grouped

