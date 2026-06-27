"""Money Flow Dashboard — tracks institutional money movement from market to stock level.

Combines market-level FII/DII flows with stock-level money flow indicators
(MFI, CMF, OBV, delivery %, volume accumulation) to identify where smart
money is flowing across Nifty 100 stocks.
"""

import os
import json
import time
import random
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict

import pandas as pd
import numpy as np

from technicals.indicators import compute_all_indicators
from technicals.data_fetcher import fetch_daily_ohlcv
from dashboard.nifty100 import NIFTY_100
from shared.utils import logger

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class StockMoneyFlow:
    ticker: str
    date: str = ""
    close: Optional[float] = None
    change_1d: Optional[float] = None

    # Money Flow Index (volume-weighted RSI)
    mfi: Optional[float] = None
    mfi_signal: str = "neutral"  # strong_inflow, inflow, outflow, strong_outflow

    # Chaikin Money Flow
    cmf: Optional[float] = None
    cmf_signal: str = "neutral"  # accumulation, strong_accumulation, distribution, strong_distribution

    # OBV trend
    obv_trend: str = "neutral"  # rising, falling, flat
    obv_divergence: str = "none"  # bullish_div, bearish_div, none

    # Volume analysis
    vol_ratio: Optional[float] = None
    vol_trend_5d: Optional[float] = None   # 5-day avg volume change %
    vol_trend_20d: Optional[float] = None  # 20-day avg volume change %

    # Delivery % proxy (inferred from price action + volume)
    accumulation_signal: str = "neutral"  # accumulating, distributing, neutral

    # Multi-timeframe money flow
    flow_1d: Optional[float] = None   # daily money flow score
    flow_5d: Optional[float] = None   # weekly
    flow_20d: Optional[float] = None  # monthly

    # Composite
    money_flow_score: int = 0  # -10 to +10
    action: str = "NEUTRAL"    # STRONG INFLOW, INFLOW, NEUTRAL, OUTFLOW, STRONG OUTFLOW
    reasons: List[str] = field(default_factory=list)


def _safe(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


def analyze_money_flow(ticker: str, df: pd.DataFrame) -> Optional[StockMoneyFlow]:
    """Analyze money flow for a single stock across timeframes."""
    if df is None or len(df) < 50:
        return None

    df = compute_all_indicators(df)
    last = df.iloc[-1]
    date_str = str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1])

    mf = StockMoneyFlow(ticker=ticker, date=date_str)
    mf.close = _safe(last["Close"])

    if len(df) >= 2:
        mf.change_1d = _safe((last["Close"] / df["Close"].iloc[-2] - 1) * 100)

    # ── MFI ──────────────────────────────────────────────────────
    mfi_val = _safe(last.get("MFI"))
    mf.mfi = mfi_val
    if mfi_val is not None:
        if mfi_val >= 80:
            mf.mfi_signal = "strong_inflow"
        elif mfi_val >= 60:
            mf.mfi_signal = "inflow"
        elif mfi_val <= 20:
            mf.mfi_signal = "strong_outflow"
        elif mfi_val <= 40:
            mf.mfi_signal = "outflow"

    # ── CMF ──────────────────────────────────────────────────────
    cmf_val = _safe(last.get("CMF"))
    mf.cmf = cmf_val
    if cmf_val is not None:
        if cmf_val >= 0.15:
            mf.cmf_signal = "strong_accumulation"
        elif cmf_val >= 0.05:
            mf.cmf_signal = "accumulation"
        elif cmf_val <= -0.15:
            mf.cmf_signal = "strong_distribution"
        elif cmf_val <= -0.05:
            mf.cmf_signal = "distribution"

    # ── OBV trend ────────────────────────────────────────────────
    if "OBV" in df.columns and "OBV_SMA_20" in df.columns:
        obv_now = last.get("OBV")
        obv_sma = last.get("OBV_SMA_20")
        if obv_now is not None and obv_sma is not None and not np.isnan(obv_now) and not np.isnan(obv_sma):
            if obv_now > obv_sma * 1.02:
                mf.obv_trend = "rising"
            elif obv_now < obv_sma * 0.98:
                mf.obv_trend = "falling"
            else:
                mf.obv_trend = "flat"

        # OBV divergence: price falling but OBV rising = bullish divergence
        if len(df) >= 20:
            price_20d = (df["Close"].iloc[-1] / df["Close"].iloc[-20] - 1) * 100
            obv_start = df["OBV"].iloc[-20]
            obv_end = df["OBV"].iloc[-1]
            if obv_start != 0:
                obv_20d = (obv_end / obv_start - 1) * 100 if obv_start > 0 else 0
            else:
                obv_20d = 0

            if price_20d < -2 and obv_20d > 5:
                mf.obv_divergence = "bullish_div"
            elif price_20d > 2 and obv_20d < -5:
                mf.obv_divergence = "bearish_div"

    # ── Volume trends ────────────────────────────────────────────
    mf.vol_ratio = _safe(last.get("Volume_Ratio"))

    if len(df) >= 10:
        vol_5d_avg = df["Volume"].iloc[-5:].mean()
        vol_prev_5d_avg = df["Volume"].iloc[-10:-5].mean()
        if vol_prev_5d_avg > 0:
            mf.vol_trend_5d = _safe((vol_5d_avg / vol_prev_5d_avg - 1) * 100)

    if len(df) >= 40:
        vol_20d_avg = df["Volume"].iloc[-20:].mean()
        vol_prev_20d_avg = df["Volume"].iloc[-40:-20].mean()
        if vol_prev_20d_avg > 0:
            mf.vol_trend_20d = _safe((vol_20d_avg / vol_prev_20d_avg - 1) * 100)

    # ── Accumulation pattern detection ───────────────────────────
    # Smart money accumulation: volume rising while price stays flat/tight range
    if len(df) >= 20 and mf.vol_trend_20d is not None:
        price_range_20d = (df["High"].iloc[-20:].max() - df["Low"].iloc[-20:].min()) / df["Close"].iloc[-20:].mean() * 100
        if mf.vol_trend_20d > 20 and price_range_20d < 10:
            mf.accumulation_signal = "accumulating"
        elif mf.vol_trend_20d < -20 and price_range_20d < 10:
            mf.accumulation_signal = "distributing"

    # ── Multi-timeframe money flow scores ────────────────────────
    # Daily: MFI direction + CMF sign + volume
    mf.flow_1d = _compute_daily_flow(df)
    mf.flow_5d = _compute_period_flow(df, 5)
    mf.flow_20d = _compute_period_flow(df, 20)

    # ── Composite Score (-10 to +10) ─────────────────────────────
    score = 0
    reasons = []

    # MFI contribution (-2 to +2)
    if mf.mfi_signal == "strong_inflow":
        score += 2
        reasons.append(f"MFI strong inflow ({mf.mfi:.0f})")
    elif mf.mfi_signal == "inflow":
        score += 1
        reasons.append(f"MFI inflow ({mf.mfi:.0f})")
    elif mf.mfi_signal == "strong_outflow":
        score -= 2
        reasons.append(f"MFI strong outflow ({mf.mfi:.0f})")
    elif mf.mfi_signal == "outflow":
        score -= 1
        reasons.append(f"MFI outflow ({mf.mfi:.0f})")

    # CMF contribution (-2 to +2)
    if mf.cmf_signal == "strong_accumulation":
        score += 2
        reasons.append(f"CMF strong accumulation ({mf.cmf:+.2f})")
    elif mf.cmf_signal == "accumulation":
        score += 1
        reasons.append(f"CMF accumulation ({mf.cmf:+.2f})")
    elif mf.cmf_signal == "strong_distribution":
        score -= 2
        reasons.append(f"CMF strong distribution ({mf.cmf:+.2f})")
    elif mf.cmf_signal == "distribution":
        score -= 1
        reasons.append(f"CMF distribution ({mf.cmf:+.2f})")

    # OBV trend (-1 to +1)
    if mf.obv_trend == "rising":
        score += 1
        reasons.append("OBV rising (accumulation)")
    elif mf.obv_trend == "falling":
        score -= 1
        reasons.append("OBV falling (distribution)")

    # OBV divergence (-1 to +2) — divergence is a powerful signal
    if mf.obv_divergence == "bullish_div":
        score += 2
        reasons.append("Bullish OBV divergence (smart money buying the dip)")
    elif mf.obv_divergence == "bearish_div":
        score -= 1
        reasons.append("Bearish OBV divergence (smart money exiting)")

    # Volume trend confirmation (-1 to +1)
    if mf.vol_trend_5d is not None and mf.vol_trend_5d > 30:
        score += 1
        reasons.append(f"Volume surging +{mf.vol_trend_5d:.0f}% vs prior week")
    elif mf.vol_trend_5d is not None and mf.vol_trend_5d < -30:
        score -= 1
        reasons.append(f"Volume drying up {mf.vol_trend_5d:.0f}% vs prior week")

    # Accumulation pattern (+2 / -1)
    if mf.accumulation_signal == "accumulating":
        score += 2
        reasons.append("Quiet accumulation pattern (rising volume, tight price)")
    elif mf.accumulation_signal == "distributing":
        score -= 1
        reasons.append("Distribution pattern (falling volume, tight price)")

    mf.money_flow_score = max(-10, min(10, score))
    mf.reasons = reasons

    if mf.money_flow_score >= 5:
        mf.action = "STRONG BUY"
    elif mf.money_flow_score >= 3:
        mf.action = "BUY"
    elif mf.money_flow_score >= 1:
        mf.action = "WATCH"
    elif mf.money_flow_score <= -4:
        mf.action = "SELL"
    elif mf.money_flow_score <= -2:
        mf.action = "AVOID"
    else:
        mf.action = "HOLD"

    return mf


def _compute_daily_flow(df: pd.DataFrame) -> Optional[float]:
    """Compute single-day money flow as a normalized score (-100 to +100)."""
    if len(df) < 2:
        return None
    last = df.iloc[-1]
    tp = (last["High"] + last["Low"] + last["Close"]) / 3
    prev_tp = (df["High"].iloc[-2] + df["Low"].iloc[-2] + df["Close"].iloc[-2]) / 3
    if prev_tp == 0:
        return 0
    # Positive if money flowing in (price up with volume)
    direction = 1 if tp > prev_tp else (-1 if tp < prev_tp else 0)
    vol_ratio = last.get("Volume_Ratio", 1)
    if pd.isna(vol_ratio):
        vol_ratio = 1
    return _safe(direction * min(vol_ratio, 3) * 33)  # normalize to ~-100 to +100


def _compute_period_flow(df: pd.DataFrame, days: int) -> Optional[float]:
    """Compute aggregate money flow over N days as a score (-100 to +100)."""
    if len(df) < days + 1:
        return None

    recent = df.iloc[-days:]
    tp = (recent["High"] + recent["Low"] + recent["Close"]) / 3
    tp_diff = tp.diff()

    pos_flow = (tp_diff > 0).sum()
    neg_flow = (tp_diff < 0).sum()
    total = pos_flow + neg_flow
    if total == 0:
        return 0

    # Net flow ratio scaled to -100 to +100
    net = (pos_flow - neg_flow) / total * 100

    # Weight by volume trend
    vol_start = recent["Volume"].iloc[:days//2].mean()
    vol_end = recent["Volume"].iloc[days//2:].mean()
    if vol_start > 0:
        vol_factor = min(vol_end / vol_start, 2.0)
    else:
        vol_factor = 1.0

    return _safe(net * vol_factor * 0.5)


# ═══════════════════════════════════════════════════════════════
# FII/DII Market-Level Flow Fetcher
# ═══════════════════════════════════════════════════════════════

def fetch_fii_dii_flows() -> Optional[List[dict]]:
    """Fetch recent FII/DII daily flow data from NSE.

    Returns list of dicts with date, category, buy, sell, net.
    Uses daily cache — only hits NSE once per day.
    """
    from shared.utils import daily_cache_get, daily_cache_set

    cached = daily_cache_get("fii_dii_flows")
    if cached is not None:
        return cached

    import requests

    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }

    try:
        session = requests.Session()
        session.get("https://www.nseindia.com/", headers=headers, timeout=10)
        resp = session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        flows = []
        for entry in data:
            category = entry.get("category", "")
            date_str = entry.get("date", "")
            buy = float(entry.get("buyValue", 0))
            sell = float(entry.get("sellValue", 0))
            net = float(entry.get("netValue", 0))

            flows.append({
                "date": date_str,
                "category": category,
                "buy": buy,
                "sell": sell,
                "net": net,
            })

        logger.info(f"Fetched {len(flows)} FII/DII flow entries from NSE")
        daily_cache_set("fii_dii_flows", flows)
        return flows

    except Exception as e:
        logger.warning(f"Could not fetch FII/DII flows from NSE: {e}")
        return None


def _signal_to_dict(sig: StockMoneyFlow) -> dict:
    d = asdict(sig)
    for k, v in d.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            d[k] = None
    return d

