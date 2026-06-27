"""Technical signal generator — combines indicators into actionable signals.

Takes computed indicator DataFrame and produces a structured signal
assessment for each stock.
"""

from dataclasses import dataclass, field
from typing import Optional, List

import pandas as pd
import numpy as np

from technicals.indicators import (
    compute_all_indicators,
    rsi_signal, macd_signal, cpr_signal,
    volume_signal, ma_trend,
)
from technicals.data_fetcher import fetch_daily_ohlcv
from shared.utils import logger


@dataclass
class TechnicalSignal:
    ticker: str
    date: str                    # analysis date

    # Current price context
    close: Optional[float] = None
    change_1d: Optional[float] = None   # % change
    change_5d: Optional[float] = None
    change_20d: Optional[float] = None

    # Individual indicators
    rsi: Optional[float] = None
    rsi_signal: str = "neutral"         # oversold, overbought, neutral

    macd_signal: str = "neutral"        # bullish_crossover, bearish_crossover, bullish, bearish
    macd_value: Optional[float] = None
    macd_histogram: Optional[float] = None

    cpr_signal: str = "neutral"         # above_cpr, below_cpr, within_cpr, narrow_range
    cpr_pivot: Optional[float] = None
    cpr_tc: Optional[float] = None
    cpr_bc: Optional[float] = None
    cpr_r1: Optional[float] = None
    cpr_s1: Optional[float] = None

    volume_signal: str = "normal"       # high_volume_up, high_volume_down, volume_spike, volume_dry
    volume_ratio: Optional[float] = None

    trend: str = "sideways"             # strong_uptrend, uptrend, downtrend, strong_downtrend, sideways
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None

    # Composite assessment
    score: int = 0                      # -5 to +5
    action: str = "HOLD"               # STRONG BUY, BUY, HOLD, SELL, STRONG SELL
    reasons: List[str] = field(default_factory=list)


def analyze_ticker(ticker: str, days: int = 365) -> Optional[TechnicalSignal]:
    """Run full technical analysis on a single ticker."""
    df = fetch_daily_ohlcv(ticker, days=days)
    if df is None:
        return None

    return _analyze_dataframe(ticker, df)


def analyze_from_dataframe(ticker: str, df: pd.DataFrame) -> Optional[TechnicalSignal]:
    """Run technical analysis on pre-fetched data."""
    return _analyze_dataframe(ticker, df)


def _analyze_dataframe(ticker: str, df: pd.DataFrame) -> Optional[TechnicalSignal]:
    """Core analysis logic."""
    df = compute_all_indicators(df)

    last = df.iloc[-1]
    date_str = str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1])

    signal = TechnicalSignal(ticker=ticker, date=date_str)
    signal.close = last["Close"]

    # Price changes
    if len(df) >= 2:
        signal.change_1d = (last["Close"] / df["Close"].iloc[-2] - 1) * 100
    if len(df) >= 6:
        signal.change_5d = (last["Close"] / df["Close"].iloc[-6] - 1) * 100
    if len(df) >= 21:
        signal.change_20d = (last["Close"] / df["Close"].iloc[-21] - 1) * 100

    # RSI
    signal.rsi = last.get("RSI")
    if signal.rsi is not None and not np.isnan(signal.rsi):
        signal.rsi_signal = rsi_signal(signal.rsi)
    else:
        signal.rsi = None

    # MACD
    signal.macd_signal = macd_signal(df)
    signal.macd_value = last.get("MACD")
    signal.macd_histogram = last.get("MACD_Histogram")
    if signal.macd_value is not None and np.isnan(signal.macd_value):
        signal.macd_value = None
    if signal.macd_histogram is not None and np.isnan(signal.macd_histogram):
        signal.macd_histogram = None

    # CPR
    signal.cpr_signal = cpr_signal(df)
    signal.cpr_pivot = last.get("CPR_Pivot")
    signal.cpr_tc = last.get("CPR_TC")
    signal.cpr_bc = last.get("CPR_BC")
    signal.cpr_r1 = last.get("CPR_R1")
    signal.cpr_s1 = last.get("CPR_S1")
    for attr in ["cpr_pivot", "cpr_tc", "cpr_bc", "cpr_r1", "cpr_s1"]:
        v = getattr(signal, attr)
        if v is not None and np.isnan(v):
            setattr(signal, attr, None)

    # Volume
    signal.volume_signal = volume_signal(df)
    signal.volume_ratio = last.get("Volume_Ratio")
    if signal.volume_ratio is not None and np.isnan(signal.volume_ratio):
        signal.volume_ratio = None

    # Trend
    signal.trend = ma_trend(df)
    signal.sma_50 = last.get("SMA_50")
    signal.sma_200 = last.get("SMA_200")
    for attr in ["sma_50", "sma_200"]:
        v = getattr(signal, attr)
        if v is not None and np.isnan(v):
            setattr(signal, attr, None)

    # ── Composite Score (-5 to +5) ───────────────────────────────────────
    score = 0
    reasons = []

    # RSI contribution (-2 to +2)
    if signal.rsi_signal == "oversold":
        score += 2
        reasons.append(f"RSI oversold ({signal.rsi:.0f})")
    elif signal.rsi_signal == "overbought":
        score -= 2
        reasons.append(f"RSI overbought ({signal.rsi:.0f})")

    # MACD contribution (-1 to +2)
    if signal.macd_signal == "bullish_crossover":
        score += 2
        reasons.append("MACD bullish crossover")
    elif signal.macd_signal == "bearish_crossover":
        score -= 1
        reasons.append("MACD bearish crossover")
    elif signal.macd_signal == "bullish":
        score += 1
        reasons.append("MACD bullish")

    # CPR contribution (-1 to +1)
    if signal.cpr_signal == "above_cpr":
        score += 1
        reasons.append("Price above CPR (bullish)")
    elif signal.cpr_signal == "below_cpr":
        score -= 1
        reasons.append("Price below CPR (bearish)")
    elif signal.cpr_signal == "narrow_range":
        reasons.append("Narrow CPR — breakout imminent")

    # Volume confirmation (+1 / -1)
    if signal.volume_signal == "high_volume_up":
        score += 1
        reasons.append(f"High volume rally ({signal.volume_ratio:.1f}x avg)")
    elif signal.volume_signal == "high_volume_down":
        score -= 1
        reasons.append(f"High volume decline ({signal.volume_ratio:.1f}x avg)")

    # Trend context
    if signal.trend in ("strong_uptrend", "uptrend"):
        reasons.append(f"Trend: {signal.trend.replace('_', ' ')}")
    elif signal.trend in ("strong_downtrend", "downtrend"):
        reasons.append(f"Trend: {signal.trend.replace('_', ' ')}")

    signal.score = max(-5, min(5, score))
    signal.reasons = reasons

    # ── Action mapping ───────────────────────────────────────────────────
    if signal.score >= 4:
        signal.action = "STRONG BUY"
    elif signal.score >= 2:
        signal.action = "BUY"
    elif signal.score <= -3:
        signal.action = "STRONG SELL"
    elif signal.score <= -1:
        signal.action = "SELL"
    else:
        signal.action = "HOLD"

    logger.info(f"{ticker}: Technical {signal.action} (score={signal.score}, "
                f"RSI={signal.rsi_signal}, MACD={signal.macd_signal}, "
                f"CPR={signal.cpr_signal}, Vol={signal.volume_signal})")

    return signal
