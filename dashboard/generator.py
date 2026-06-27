"""Nifty 100 Dashboard Generator.

Fetches daily data for all Nifty 100 stocks, computes technical indicators,
scores them for short-term positional trading, and generates a self-contained
HTML dashboard.
"""

import os
import json
import time
import random
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List

import pandas as pd
import numpy as np

from technicals.indicators import (
    compute_all_indicators,
    rsi_signal, macd_signal, cpr_signal, volume_signal, ma_trend,
    adx_signal, bollinger_signal, supertrend_signal, stochrsi_signal,
    ema_crossover_signal, vwap_signal, ttm_squeeze_signal,
    ichimoku_signal, relative_strength_signal, vcp_signal,
)
from technicals.data_fetcher import fetch_daily_ohlcv
from dashboard.nifty100 import NIFTY_100
from shared.utils import logger

NIFTY50_SYMBOL = "^NSEI"

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class DashboardSignal:
    ticker: str
    date: str = ""

    # Price
    close: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None
    change_1d: Optional[float] = None
    change_5d: Optional[float] = None
    change_20d: Optional[float] = None

    # Indicators
    rsi: Optional[float] = None
    rsi_signal: str = "neutral"

    macd_signal: str = "neutral"
    macd_histogram: Optional[float] = None

    adx: Optional[float] = None
    adx_signal: str = "no_trend"
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None

    bb_signal: str = "neutral"
    bb_pctb: Optional[float] = None
    bb_width: Optional[float] = None

    supertrend_signal: str = "neutral"
    supertrend_value: Optional[float] = None

    stochrsi_signal: str = "neutral"
    stochrsi_k: Optional[float] = None
    stochrsi_d: Optional[float] = None

    volume_signal: str = "normal"
    volume_ratio: Optional[float] = None

    trend: str = "sideways"
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None

    cpr_signal: str = "neutral"

    ema_cross_signal: str = "neutral"
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None

    # New world-class strategy signals
    vwap_signal: str = "neutral"
    vwap_value: Optional[float] = None
    ttm_squeeze_signal: str = "no_squeeze"
    ichimoku_signal: str = "neutral"
    rs_signal: str = "neutral"
    rs_ratio: Optional[float] = None
    vcp_signal: str = "no_pattern"
    vcp_score: Optional[float] = None

    # Composite
    score: int = 0
    max_score: int = 16
    action: str = "HOLD"
    reasons: List[str] = field(default_factory=list)


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        i = int(val)
        return i
    except (TypeError, ValueError):
        return None


def analyze_for_dashboard(ticker: str, df: pd.DataFrame,
                           benchmark_df: pd.DataFrame = None) -> Optional[DashboardSignal]:
    """Analyze a single ticker for the dashboard with positional trading scoring."""
    if df is None or len(df) < 30:
        return None

    df = compute_all_indicators(df, benchmark_df=benchmark_df)
    last = df.iloc[-1]
    date_str = str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1])

    sig = DashboardSignal(ticker=ticker, date=date_str)

    # Price context
    sig.close = _safe_float(last["Close"])
    sig.open = _safe_float(last["Open"])
    sig.high = _safe_float(last["High"])
    sig.low = _safe_float(last["Low"])
    sig.volume = _safe_int(last.get("Volume"))

    if len(df) >= 2:
        sig.change_1d = _safe_float((last["Close"] / df["Close"].iloc[-2] - 1) * 100)
    if len(df) >= 6:
        sig.change_5d = _safe_float((last["Close"] / df["Close"].iloc[-6] - 1) * 100)
    if len(df) >= 21:
        sig.change_20d = _safe_float((last["Close"] / df["Close"].iloc[-21] - 1) * 100)

    # Individual indicators
    sig.rsi = _safe_float(last.get("RSI"))
    sig.rsi_signal = rsi_signal(sig.rsi) if sig.rsi else "neutral"

    sig.macd_signal = macd_signal(df)
    sig.macd_histogram = _safe_float(last.get("MACD_Histogram"))

    sig.adx = _safe_float(last.get("ADX"))
    sig.adx_signal = adx_signal(df)
    sig.plus_di = _safe_float(last.get("Plus_DI"))
    sig.minus_di = _safe_float(last.get("Minus_DI"))

    sig.bb_signal = bollinger_signal(df)
    sig.bb_pctb = _safe_float(last.get("BB_PctB"))
    sig.bb_width = _safe_float(last.get("BB_Width"))

    sig.supertrend_signal = supertrend_signal(df)
    sig.supertrend_value = _safe_float(last.get("SuperTrend"))

    sig.stochrsi_signal = stochrsi_signal(df)
    sig.stochrsi_k = _safe_float(last.get("StochRSI_K"))
    sig.stochrsi_d = _safe_float(last.get("StochRSI_D"))

    sig.volume_signal = volume_signal(df)
    sig.volume_ratio = _safe_float(last.get("Volume_Ratio"))

    sig.trend = ma_trend(df)
    sig.sma_20 = _safe_float(last.get("SMA_20"))
    sig.sma_50 = _safe_float(last.get("SMA_50"))
    sig.sma_200 = _safe_float(last.get("SMA_200"))

    sig.cpr_signal = cpr_signal(df)

    sig.ema_cross_signal = ema_crossover_signal(df)
    sig.ema_20 = _safe_float(last.get("EMA_20"))
    sig.ema_50 = _safe_float(last.get("EMA_50"))

    # New world-class strategy signals
    sig.vwap_signal = vwap_signal(df)
    sig.vwap_value = _safe_float(last.get("VWAP"))
    sig.ttm_squeeze_signal = ttm_squeeze_signal(df)
    sig.ichimoku_signal = ichimoku_signal(df)
    sig.rs_signal = relative_strength_signal(df)
    sig.rs_ratio = _safe_float(last.get("RS_Ratio"))
    sig.vcp_signal = vcp_signal(df)
    sig.vcp_score = _safe_float(last.get("VCP_Score"))

    # ══════════════════════════════════════════════════════════════
    # BACKTEST-CALIBRATED SCORING (-16 to +16)
    #
    # Weights derived from 3-year Nifty 100 backtest (May 2026):
    #
    # SCORING INDICATORS (>55% WR):
    #   EMA 20/50 Cross:   63% WR, 2.3 PF  → weight 3 (best PF)
    #   RSI Oversold:      62% WR, 2.2 PF  → weight 3
    #   BB Lower Touch:    58% WR, 1.8 PF  → weight 2
    #   Vol Spike Up:      58% WR, 2.0 PF  → weight 2 (upgraded)
    #   RS vs Nifty:       57% WR, 1.7 PF  → weight 2 (NEW)
    #   StochRSI Cross:    57% WR, 1.8 PF  → weight 1
    #   MACD Cross:        56% WR, 1.7 PF  → weight 1
    #   VWAP Reclaim:      56% WR, 1.7 PF  → weight 1 (NEW)
    #   MACD+EMA combo:    tested pair PF 2.1 → +1 bonus
    #
    # DISPLAY-ONLY (≤55% WR):
    #   Ichimoku TK+Cloud: 55% WR, 1.5 PF  → display only
    #   TTM Squeeze Fire:  55% WR, 1.4 PF  → display only
    #   Minervini VCP:     54% WR, 1.7 PF  → display only
    #   SuperTrend Flip:   56% WR, 1.6 PF  → display only
    #   ADX Trend Up:      51% WR, 1.4 PF  → display only
    #   CPR Breakout:      57% WR, 1.8 PF  → display only (too noisy)
    # ══════════════════════════════════════════════════════════════
    score = 0
    reasons = []

    # ── EMA 20/50: weight 3 (63% WR, 2.3 PF — best in 3Y) ──────
    if sig.ema_cross_signal == "bullish_crossover":
        score += 3
        reasons.append("EMA 20/50 bullish crossover [63% WR, 2.3 PF]")
    elif sig.ema_cross_signal == "bearish_crossover":
        score -= 2
        reasons.append("EMA 20/50 bearish crossover")

    # ── RSI: weight 3 (62% WR, 2.2 PF) ──────────────────────────
    if sig.rsi_signal == "oversold":
        score += 3
        reasons.append(f"RSI oversold ({sig.rsi:.0f}) [62% WR]")
    elif sig.rsi_signal == "overbought":
        score -= 2
        reasons.append(f"RSI overbought ({sig.rsi:.0f})")

    # ── Bollinger Lower: weight 2 (58% WR, 1.8 PF) ─────────────
    if sig.bb_signal == "lower_band_touch":
        score += 2
        reasons.append("BB lower band touch [58% WR]")
    elif sig.bb_signal == "walking_lower":
        score -= 1
        reasons.append("Walking BB lower band")
    elif sig.bb_signal == "walking_upper":
        score += 1
        reasons.append("Walking BB upper (strong trend)")
    elif sig.bb_signal == "upper_band_touch":
        score -= 1
        reasons.append("BB upper band (extended)")

    # ── Volume Spike: weight 2 (58% WR, 2.0 PF — upgraded) ─────
    if sig.volume_signal == "high_volume_up":
        score += 2
        reasons.append(f"High volume rally ({sig.volume_ratio:.1f}x) [58% WR]")
    elif sig.volume_signal == "high_volume_down":
        score -= 1
        reasons.append(f"High volume decline ({sig.volume_ratio:.1f}x)")

    # ── RS vs Nifty: weight 2 (57% WR, 1.7 PF — NEW) ───────────
    if sig.rs_signal == "rs_new_high":
        score += 2
        reasons.append("RS vs Nifty at new high [57% WR]")
    elif sig.rs_signal == "rs_improving":
        score += 1
        reasons.append("RS vs Nifty improving")
    elif sig.rs_signal == "rs_new_low":
        score -= 1
        reasons.append("RS vs Nifty at new low")

    # ── StochRSI: weight 1 (57% WR, 1.8 PF) ────────────────────
    if sig.stochrsi_signal == "oversold_crossover":
        score += 1
        reasons.append("StochRSI oversold crossover [57% WR]")
    elif sig.stochrsi_signal == "overbought_crossover":
        score -= 1
        reasons.append("StochRSI overbought crossover")

    # ── MACD: weight 1 (56% WR, 1.7 PF) ─────────────────────────
    if sig.macd_signal == "bullish_crossover":
        score += 1
        reasons.append("MACD bullish crossover [56% WR]")
    elif sig.macd_signal == "bearish_crossover":
        score -= 1
        reasons.append("MACD bearish crossover")

    # ── VWAP Reclaim: weight 1 (56% WR, 1.7 PF — NEW) ──────────
    if sig.vwap_signal == "vwap_reclaim":
        score += 1
        reasons.append("VWAP reclaim (institutional buy) [56% WR]")
    elif sig.vwap_signal == "below_vwap":
        pass  # no penalty, just context

    # ── COMBO BONUS ──────────────────────────────────────────────
    # MACD + EMA 20/50 combo: 2.1 PF pair synergy
    if (sig.macd_signal in ("bullish_crossover", "bullish") and
            sig.ema_cross_signal in ("bullish_crossover", "bullish")):
        score += 1
        reasons.append("MACD + EMA combo bonus [2.1 PF]")

    # ── Display-only indicators (no scoring weight) ──────────────
    if sig.supertrend_signal in ("bullish_flip", "bullish"):
        reasons.append(f"SuperTrend {sig.supertrend_signal.replace('_', ' ')} (display)")
    elif sig.supertrend_signal in ("bearish_flip", "bearish"):
        reasons.append(f"SuperTrend {sig.supertrend_signal.replace('_', ' ')} (display)")

    if sig.adx_signal in ("strong_trend_up", "trending_up"):
        reasons.append(f"ADX uptrend ({sig.adx:.0f}) (display)")
    elif sig.adx_signal in ("strong_trend_down", "trending_down"):
        reasons.append(f"ADX downtrend ({sig.adx:.0f}) (display)")

    if sig.ichimoku_signal == "tk_cross_above_cloud":
        reasons.append("Ichimoku TK cross above cloud (display)")
    elif sig.ichimoku_signal == "bullish_above_cloud":
        reasons.append("Ichimoku bullish above cloud (display)")
    elif sig.ichimoku_signal == "bearish_below_cloud":
        reasons.append("Ichimoku bearish below cloud (display)")

    if sig.ttm_squeeze_signal == "squeeze_fire_up":
        reasons.append("TTM Squeeze fired UP (display)")
    elif sig.ttm_squeeze_signal == "in_squeeze":
        reasons.append("TTM Squeeze building (display)")

    if sig.vcp_signal == "vcp_breakout":
        reasons.append("Minervini VCP breakout (display)")
    elif sig.vcp_signal == "vcp_forming":
        reasons.append("VCP forming (display)")

    if sig.trend in ("strong_uptrend", "uptrend"):
        reasons.append(f"MA trend: {sig.trend.replace('_', ' ')}")
    elif sig.trend in ("strong_downtrend", "downtrend"):
        reasons.append(f"MA trend: {sig.trend.replace('_', ' ')}")

    sig.score = max(-16, min(16, score))
    sig.reasons = reasons

    # Action mapping
    if sig.score >= 7:
        sig.action = "STRONG BUY"
    elif sig.score >= 4:
        sig.action = "BUY"
    elif sig.score >= 1:
        sig.action = "WATCH"
    elif sig.score <= -5:
        sig.action = "STRONG SELL"
    elif sig.score <= -2:
        sig.action = "SELL"
    else:
        sig.action = "HOLD"

    return sig


def _signal_to_dict(sig: DashboardSignal) -> dict:
    """Convert signal to JSON-serializable dict."""
    d = asdict(sig)
    for k, v in d.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            d[k] = None
    return d
