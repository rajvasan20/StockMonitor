"""Single-indicator backtester for Nifty 100.

Tests each technical indicator's buy signal independently across all stocks
over the past year. Measures forward returns at 5D, 10D, 20D horizons
to determine which indicators actually work for positional trading.
"""

import os
import time
import random
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

import pandas as pd
import numpy as np

from technicals.indicators import (
    compute_all_indicators,
    rsi_signal, macd_signal, cpr_signal, volume_signal, ma_trend,
    adx_signal, bollinger_signal, supertrend_signal, stochrsi_signal,
    vwap_signal, ttm_squeeze_signal, ichimoku_signal,
    relative_strength_signal, vcp_signal,
)
from technicals.data_fetcher import fetch_daily_ohlcv
from dashboard.nifty100 import NIFTY_100
from shared.utils import logger

NIFTY50_SYMBOL = "^NSEI"  # Nifty 50 index on Yahoo Finance

HORIZONS = [5, 10, 20]  # trading days forward


@dataclass
class TradeResult:
    """A single simulated trade triggered by an indicator signal."""
    ticker: str
    entry_date: str
    entry_price: float
    returns_5d: Optional[float] = None   # % return
    returns_10d: Optional[float] = None
    returns_20d: Optional[float] = None
    max_drawdown: Optional[float] = None  # worst intra-trade drawdown %


@dataclass
class IndicatorBacktest:
    """Backtest results for a single indicator."""
    indicator: str
    signal_name: str          # e.g. "RSI Oversold (<=30)"
    total_signals: int = 0
    trades: List[TradeResult] = field(default_factory=list)

    # Computed stats
    win_rate_5d: Optional[float] = None
    win_rate_10d: Optional[float] = None
    win_rate_20d: Optional[float] = None
    avg_return_5d: Optional[float] = None
    avg_return_10d: Optional[float] = None
    avg_return_20d: Optional[float] = None
    median_return_5d: Optional[float] = None
    median_return_10d: Optional[float] = None
    median_return_20d: Optional[float] = None
    avg_max_drawdown: Optional[float] = None
    profit_factor_20d: Optional[float] = None  # gross profit / gross loss
    stocks_with_signals: int = 0

    def compute_stats(self):
        if not self.trades:
            return

        r5 = [t.returns_5d for t in self.trades if t.returns_5d is not None]
        r10 = [t.returns_10d for t in self.trades if t.returns_10d is not None]
        r20 = [t.returns_20d for t in self.trades if t.returns_20d is not None]
        dd = [t.max_drawdown for t in self.trades if t.max_drawdown is not None]

        if r5:
            self.win_rate_5d = round(sum(1 for r in r5 if r > 0) / len(r5) * 100, 1)
            self.avg_return_5d = round(np.mean(r5), 2)
            self.median_return_5d = round(np.median(r5), 2)

        if r10:
            self.win_rate_10d = round(sum(1 for r in r10 if r > 0) / len(r10) * 100, 1)
            self.avg_return_10d = round(np.mean(r10), 2)
            self.median_return_10d = round(np.median(r10), 2)

        if r20:
            self.win_rate_20d = round(sum(1 for r in r20 if r > 0) / len(r20) * 100, 1)
            self.avg_return_20d = round(np.mean(r20), 2)
            self.median_return_20d = round(np.median(r20), 2)

            # Profit factor
            gross_profit = sum(r for r in r20 if r > 0)
            gross_loss = abs(sum(r for r in r20 if r < 0))
            self.profit_factor_20d = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

        if dd:
            self.avg_max_drawdown = round(np.mean(dd), 2)


# ═══════════════════════════════════════════════════════════════
# Signal detection functions — each returns list of indices where
# the buy signal fired
# ═══════════════════════════════════════════════════════════════

def _detect_rsi_oversold(df: pd.DataFrame) -> List[int]:
    """RSI crosses below 30 (oversold entry)."""
    indices = []
    if "RSI" not in df.columns:
        return indices
    rsi = df["RSI"]
    for i in range(1, len(df)):
        if pd.notna(rsi.iloc[i]) and rsi.iloc[i] <= 30 and pd.notna(rsi.iloc[i-1]) and rsi.iloc[i-1] > 30:
            indices.append(i)
    return indices


def _detect_macd_bullish_crossover(df: pd.DataFrame) -> List[int]:
    """MACD histogram crosses from negative to positive."""
    indices = []
    if "MACD_Histogram" not in df.columns:
        return indices
    hist = df["MACD_Histogram"]
    for i in range(1, len(df)):
        if pd.notna(hist.iloc[i]) and pd.notna(hist.iloc[i-1]):
            if hist.iloc[i-1] <= 0 and hist.iloc[i] > 0:
                indices.append(i)
    return indices


def _detect_supertrend_bullish_flip(df: pd.DataFrame) -> List[int]:
    """SuperTrend flips from bearish to bullish."""
    indices = []
    if "SuperTrend_Direction" not in df.columns:
        return indices
    st = df["SuperTrend_Direction"]
    for i in range(1, len(df)):
        if st.iloc[i] == 1 and st.iloc[i-1] == -1:
            indices.append(i)
    return indices


def _detect_supertrend_bullish(df: pd.DataFrame) -> List[int]:
    """SuperTrend is bullish (direction = 1)."""
    indices = []
    if "SuperTrend_Direction" not in df.columns:
        return indices
    st = df["SuperTrend_Direction"]
    for i in range(len(df)):
        if st.iloc[i] == 1:
            indices.append(i)
    return indices


def _detect_adx_trending_up(df: pd.DataFrame) -> List[int]:
    """ADX > 25 and +DI > -DI (confirmed uptrend)."""
    indices = []
    if "ADX" not in df.columns:
        return indices
    for i in range(1, len(df)):
        adx = df["ADX"].iloc[i]
        plus = df["Plus_DI"].iloc[i]
        minus = df["Minus_DI"].iloc[i]
        prev_adx = df["ADX"].iloc[i-1]
        if all(pd.notna(v) for v in [adx, plus, minus, prev_adx]):
            # Signal when ADX crosses above 25 with bullish DI
            if adx >= 25 and plus > minus and prev_adx < 25:
                indices.append(i)
    return indices


def _detect_bollinger_lower_touch(df: pd.DataFrame) -> List[int]:
    """Price touches or goes below lower Bollinger Band."""
    indices = []
    if "BB_PctB" not in df.columns:
        return indices
    pctb = df["BB_PctB"]
    for i in range(1, len(df)):
        if pd.notna(pctb.iloc[i]) and pctb.iloc[i] <= 0.0 and pd.notna(pctb.iloc[i-1]) and pctb.iloc[i-1] > 0.0:
            indices.append(i)
    return indices


def _detect_bollinger_squeeze(df: pd.DataFrame) -> List[int]:
    """Bollinger Band squeeze (width in bottom 20th percentile) followed by upward break."""
    indices = []
    if "BB_Width" not in df.columns or "BB_PctB" not in df.columns:
        return indices
    width = df["BB_Width"]
    pctb = df["BB_PctB"]
    for i in range(121, len(df)):
        recent = width.iloc[i-120:i].dropna()
        if len(recent) < 20:
            continue
        curr_w = width.iloc[i]
        if pd.isna(curr_w):
            continue
        pctile = (recent < curr_w).sum() / len(recent)
        # Squeeze: width in bottom 20%, and price breaking above mid band
        if pctile < 0.2 and pd.notna(pctb.iloc[i]) and pctb.iloc[i] > 0.5:
            # Only trigger once per squeeze (check prev day wasn't also squeeze)
            prev_w = width.iloc[i-1]
            prev_recent = width.iloc[i-121:i-1].dropna()
            if len(prev_recent) >= 20:
                prev_pctile = (prev_recent < prev_w).sum() / len(prev_recent)
                if prev_pctile < 0.2:
                    continue  # already in squeeze
            indices.append(i)
    return indices


def _detect_stochrsi_oversold_crossover(df: pd.DataFrame) -> List[int]:
    """StochRSI K crosses above D in oversold zone (K < 20)."""
    indices = []
    if "StochRSI_K" not in df.columns or "StochRSI_D" not in df.columns:
        return indices
    k = df["StochRSI_K"]
    d = df["StochRSI_D"]
    for i in range(1, len(df)):
        if all(pd.notna(v) for v in [k.iloc[i], d.iloc[i], k.iloc[i-1], d.iloc[i-1]]):
            if k.iloc[i] < 20 and k.iloc[i-1] <= d.iloc[i-1] and k.iloc[i] > d.iloc[i]:
                indices.append(i)
    return indices


def _detect_volume_spike_up(df: pd.DataFrame) -> List[int]:
    """Volume >= 2x average with price up."""
    indices = []
    if "Volume_Ratio" not in df.columns:
        return indices
    for i in range(1, len(df)):
        vr = df["Volume_Ratio"].iloc[i]
        if pd.notna(vr) and vr >= 2.0:
            if df["Close"].iloc[i] > df["Close"].iloc[i-1]:
                indices.append(i)
    return indices


def _detect_cpr_above(df: pd.DataFrame) -> List[int]:
    """Price crosses above CPR Top Central."""
    indices = []
    if "CPR_TC" not in df.columns:
        return indices
    for i in range(1, len(df)):
        tc = df["CPR_TC"].iloc[i]
        close = df["Close"].iloc[i]
        prev_close = df["Close"].iloc[i-1]
        prev_tc = df["CPR_TC"].iloc[i-1]
        if all(pd.notna(v) for v in [tc, close, prev_close, prev_tc]):
            if close > tc and prev_close <= prev_tc:
                indices.append(i)
    return indices


def _detect_ema_20_50_crossover(df: pd.DataFrame) -> List[int]:
    """EMA 20 crosses above EMA 50 (golden crossover for positional)."""
    indices = []
    if "EMA_20" not in df.columns or "EMA_50" not in df.columns:
        return indices
    ema20 = df["EMA_20"]
    ema50 = df["EMA_50"]
    for i in range(1, len(df)):
        if all(pd.notna(v) for v in [ema20.iloc[i], ema50.iloc[i],
                                      ema20.iloc[i-1], ema50.iloc[i-1]]):
            if ema20.iloc[i-1] <= ema50.iloc[i-1] and ema20.iloc[i] > ema50.iloc[i]:
                indices.append(i)
    return indices


# ═══════════════════════════════════════════════════════════════
# MONEY FLOW signal detectors
# ═══════════════════════════════════════════════════════════════

def _detect_mfi_oversold(df: pd.DataFrame) -> List[int]:
    """MFI crosses below 20 (money flow oversold — reversal entry)."""
    indices = []
    if "MFI" not in df.columns:
        return indices
    mfi = df["MFI"]
    for i in range(1, len(df)):
        if pd.notna(mfi.iloc[i]) and mfi.iloc[i] <= 20 and pd.notna(mfi.iloc[i-1]) and mfi.iloc[i-1] > 20:
            indices.append(i)
    return indices


def _detect_mfi_strong_inflow(df: pd.DataFrame) -> List[int]:
    """MFI crosses above 60 (strong money inflow — momentum entry)."""
    indices = []
    if "MFI" not in df.columns:
        return indices
    mfi = df["MFI"]
    for i in range(1, len(df)):
        if pd.notna(mfi.iloc[i]) and mfi.iloc[i] >= 60 and pd.notna(mfi.iloc[i-1]) and mfi.iloc[i-1] < 60:
            indices.append(i)
    return indices


def _detect_cmf_accumulation(df: pd.DataFrame) -> List[int]:
    """CMF crosses above +0.05 (net accumulation begins)."""
    indices = []
    if "CMF" not in df.columns:
        return indices
    cmf = df["CMF"]
    for i in range(1, len(df)):
        if pd.notna(cmf.iloc[i]) and pd.notna(cmf.iloc[i-1]):
            if cmf.iloc[i] >= 0.05 and cmf.iloc[i-1] < 0.05:
                indices.append(i)
    return indices


def _detect_cmf_strong_accumulation(df: pd.DataFrame) -> List[int]:
    """CMF crosses above +0.15 (heavy institutional accumulation)."""
    indices = []
    if "CMF" not in df.columns:
        return indices
    cmf = df["CMF"]
    for i in range(1, len(df)):
        if pd.notna(cmf.iloc[i]) and pd.notna(cmf.iloc[i-1]):
            if cmf.iloc[i] >= 0.15 and cmf.iloc[i-1] < 0.15:
                indices.append(i)
    return indices


def _detect_obv_bullish_divergence(df: pd.DataFrame) -> List[int]:
    """Price falling but OBV rising over 20 days — smart money buying dip."""
    indices = []
    if "OBV" not in df.columns:
        return indices
    for i in range(20, len(df)):
        price_chg = (df["Close"].iloc[i] / df["Close"].iloc[i-20] - 1) * 100
        obv_start = df["OBV"].iloc[i-20]
        obv_end = df["OBV"].iloc[i]
        if obv_start == 0:
            continue
        obv_chg = (obv_end / obv_start - 1) * 100 if obv_start > 0 else 0
        if price_chg < -3 and obv_chg > 10:
            # Only fire once per divergence event (skip if prev day also divergent)
            if i > 20:
                prev_price_chg = (df["Close"].iloc[i-1] / df["Close"].iloc[i-21] - 1) * 100
                prev_obv_start = df["OBV"].iloc[i-21]
                if prev_obv_start > 0:
                    prev_obv_chg = (df["OBV"].iloc[i-1] / prev_obv_start - 1) * 100
                    if prev_price_chg < -3 and prev_obv_chg > 10:
                        continue
            indices.append(i)
    return indices


def _detect_quiet_accumulation(df: pd.DataFrame) -> List[int]:
    """Rising volume + tight price range over 20 days — stealth institutional buying."""
    indices = []
    if "Volume" not in df.columns:
        return indices
    for i in range(40, len(df)):
        vol_20d = df["Volume"].iloc[i-20:i].mean()
        vol_prev_20d = df["Volume"].iloc[i-40:i-20].mean()
        if vol_prev_20d == 0:
            continue
        vol_change = (vol_20d / vol_prev_20d - 1) * 100

        price_range = (df["High"].iloc[i-20:i].max() - df["Low"].iloc[i-20:i].min()) / df["Close"].iloc[i-20:i].mean() * 100

        if vol_change > 20 and price_range < 10:
            # Trigger once per pattern
            if i > 40:
                prev_vol_20d = df["Volume"].iloc[i-21:i-1].mean()
                prev_vol_prev_20d = df["Volume"].iloc[i-41:i-21].mean()
                if prev_vol_prev_20d > 0:
                    prev_vol_chg = (prev_vol_20d / prev_vol_prev_20d - 1) * 100
                    prev_range = (df["High"].iloc[i-21:i-1].max() - df["Low"].iloc[i-21:i-1].min()) / df["Close"].iloc[i-21:i-1].mean() * 100
                    if prev_vol_chg > 20 and prev_range < 10:
                        continue
            indices.append(i)
    return indices


# ═══════════════════════════════════════════════════════════════
# WORLD-CLASS STRATEGY signal detectors
# ═══════════════════════════════════════════════════════════════

def _detect_vwap_reclaim(df: pd.DataFrame) -> List[int]:
    """Price crosses from below VWAP to above VWAP (institutional reclaim)."""
    indices = []
    if "VWAP" not in df.columns:
        return indices
    close = df["Close"]
    vwap = df["VWAP"]
    for i in range(1, len(df)):
        if all(pd.notna(v) for v in [close.iloc[i], close.iloc[i-1], vwap.iloc[i], vwap.iloc[i-1]]):
            if close.iloc[i-1] < vwap.iloc[i-1] and close.iloc[i] > vwap.iloc[i]:
                indices.append(i)
    return indices


def _detect_ttm_squeeze_fire(df: pd.DataFrame) -> List[int]:
    """TTM Squeeze fires: BB were inside KC (squeeze), now released upward.

    John Carter's TTM Squeeze: volatility compression → breakout.
    """
    indices = []
    if not all(c in df.columns for c in ["BB_Upper", "BB_Lower", "KC_Upper", "KC_Lower"]):
        return indices
    for i in range(2, len(df)):
        bb_u = df["BB_Upper"].iloc[i]
        bb_l = df["BB_Lower"].iloc[i]
        kc_u = df["KC_Upper"].iloc[i]
        kc_l = df["KC_Lower"].iloc[i]
        bb_u_p = df["BB_Upper"].iloc[i-1]
        bb_l_p = df["BB_Lower"].iloc[i-1]
        kc_u_p = df["KC_Upper"].iloc[i-1]
        kc_l_p = df["KC_Lower"].iloc[i-1]

        if any(pd.isna(v) for v in [bb_u, bb_l, kc_u, kc_l, bb_u_p, bb_l_p, kc_u_p, kc_l_p]):
            continue

        in_squeeze_prev = bb_l_p > kc_l_p and bb_u_p < kc_u_p
        in_squeeze_now = bb_l > kc_l and bb_u < kc_u

        # Squeeze just released
        if in_squeeze_prev and not in_squeeze_now:
            # Only bullish fires (price up or MACD hist positive)
            if df["Close"].iloc[i] > df["Close"].iloc[i-1]:
                # Check we had at least 3 bars of squeeze before
                squeeze_count = 0
                for j in range(max(0, i-10), i):
                    bb_uj = df["BB_Upper"].iloc[j]
                    bb_lj = df["BB_Lower"].iloc[j]
                    kc_uj = df["KC_Upper"].iloc[j]
                    kc_lj = df["KC_Lower"].iloc[j]
                    if all(pd.notna(v) for v in [bb_uj, bb_lj, kc_uj, kc_lj]):
                        if bb_lj > kc_lj and bb_uj < kc_uj:
                            squeeze_count += 1
                if squeeze_count >= 3:
                    indices.append(i)
    return indices


def _detect_ichimoku_bullish(df: pd.DataFrame) -> List[int]:
    """Tenkan crosses above Kijun while price is above the cloud.

    This is the strongest Ichimoku buy signal — TK cross above cloud.
    """
    indices = []
    if not all(c in df.columns for c in ["Ichimoku_Tenkan", "Ichimoku_Kijun",
                                           "Ichimoku_SpanA", "Ichimoku_SpanB"]):
        return indices
    for i in range(1, len(df)):
        tenkan = df["Ichimoku_Tenkan"].iloc[i]
        kijun = df["Ichimoku_Kijun"].iloc[i]
        span_a = df["Ichimoku_SpanA"].iloc[i]
        span_b = df["Ichimoku_SpanB"].iloc[i]
        tenkan_p = df["Ichimoku_Tenkan"].iloc[i-1]
        kijun_p = df["Ichimoku_Kijun"].iloc[i-1]
        close = df["Close"].iloc[i]

        if any(pd.isna(v) for v in [tenkan, kijun, span_a, span_b, tenkan_p, kijun_p, close]):
            continue

        cloud_top = max(span_a, span_b)
        tk_cross = tenkan_p <= kijun_p and tenkan > kijun
        above_cloud = close > cloud_top

        if tk_cross and above_cloud:
            indices.append(i)
    return indices


def _detect_vcp_breakout(df: pd.DataFrame) -> List[int]:
    """Minervini VCP: high VCP score + price breaks above 20-day range.

    VCP = progressively tighter contractions + declining volume → breakout.
    """
    indices = []
    if "VCP_Score" not in df.columns:
        return indices
    for i in range(21, len(df)):
        score = df["VCP_Score"].iloc[i]
        if pd.isna(score) or score < 60:
            continue
        # Price breaks above 20-day high
        recent_high = df["High"].iloc[i-20:i].max()
        if pd.notna(recent_high) and df["Close"].iloc[i] > recent_high:
            # Check prev day wasn't also a breakout (de-dup)
            prev_score = df["VCP_Score"].iloc[i-1]
            prev_high = df["High"].iloc[i-21:i-1].max()
            if pd.notna(prev_score) and prev_score >= 60 and pd.notna(prev_high):
                if df["Close"].iloc[i-1] > prev_high:
                    continue  # already triggered
            indices.append(i)
    return indices


def _detect_rs_breakout(df: pd.DataFrame) -> List[int]:
    """Relative strength vs index at new 20-day high + stock pulling back.

    Buy leaders during pullbacks — stock outperforming index, price dipping to buy zone.
    """
    indices = []
    if "RS_Line" not in df.columns or "RS_SMA" not in df.columns:
        return indices
    for i in range(21, len(df)):
        rs_now = df["RS_Line"].iloc[i]
        rs_sma = df["RS_SMA"].iloc[i]
        if pd.isna(rs_now) or pd.isna(rs_sma):
            continue

        # RS improving (above its SMA)
        if rs_now <= rs_sma:
            continue

        # RS near 20-day high (within 3%)
        rs_20d_high = df["RS_Line"].iloc[i-20:i].max()
        if pd.isna(rs_20d_high) or rs_now < rs_20d_high * 0.97:
            continue

        # Price has pulled back 2-8% from recent high (buy the dip in a leader)
        price_20d_high = df["High"].iloc[i-20:i].max()
        close = df["Close"].iloc[i]
        if price_20d_high > 0:
            drawdown = (close / price_20d_high - 1) * 100
            if -8 <= drawdown <= -2:
                # De-dup
                if i > 21:
                    prev_rs = df["RS_Line"].iloc[i-1]
                    prev_rs_high = df["RS_Line"].iloc[i-21:i-1].max()
                    prev_close = df["Close"].iloc[i-1]
                    prev_price_high = df["High"].iloc[i-21:i-1].max()
                    if (pd.notna(prev_rs) and pd.notna(prev_rs_high) and
                            prev_rs >= prev_rs_high * 0.97 and prev_rs > rs_sma):
                        prev_dd = (prev_close / prev_price_high - 1) * 100
                        if -8 <= prev_dd <= -2:
                            continue
                indices.append(i)
    return indices


# ═══════════════════════════════════════════════════════════════
# Forward return calculator
# ═══════════════════════════════════════════════════════════════

def _compute_forward_returns(df: pd.DataFrame, signal_idx: int,
                              ticker: str) -> TradeResult:
    """Compute forward returns and max drawdown from a signal point."""
    entry_price = df["Close"].iloc[signal_idx]
    entry_date = str(df.index[signal_idx].date()) if hasattr(df.index[signal_idx], 'date') else str(df.index[signal_idx])

    trade = TradeResult(
        ticker=ticker,
        entry_date=entry_date,
        entry_price=entry_price,
    )

    remaining = len(df) - signal_idx - 1

    # Forward returns
    for horizon, attr in [(5, 'returns_5d'), (10, 'returns_10d'), (20, 'returns_20d')]:
        if remaining >= horizon:
            exit_price = df["Close"].iloc[signal_idx + horizon]
            ret = (exit_price / entry_price - 1) * 100
            setattr(trade, attr, round(ret, 2))

    # Max drawdown within 20-day window
    max_horizon = min(20, remaining)
    if max_horizon > 0:
        future_lows = df["Low"].iloc[signal_idx + 1: signal_idx + max_horizon + 1]
        min_low = future_lows.min()
        trade.max_drawdown = round((min_low / entry_price - 1) * 100, 2)

    return trade


# ═══════════════════════════════════════════════════════════════
# Main backtest runner
# ═══════════════════════════════════════════════════════════════

# Signal registry: (indicator_key, display_name, detector_function)
SIGNAL_REGISTRY = [
    ("rsi_oversold", "RSI Oversold (crosses below 30)", _detect_rsi_oversold),
    ("macd_crossover", "MACD Bullish Crossover", _detect_macd_bullish_crossover),
    ("supertrend_flip", "SuperTrend Bullish Flip", _detect_supertrend_bullish_flip),
    ("adx_trend_up", "ADX Uptrend Confirmation (>25, +DI>-DI)", _detect_adx_trending_up),
    ("bb_lower_touch", "Bollinger Lower Band Touch", _detect_bollinger_lower_touch),
    ("bb_squeeze", "Bollinger Squeeze + Upward Break", _detect_bollinger_squeeze),
    ("stochrsi_crossover", "StochRSI Oversold Crossover (K<20, K>D)", _detect_stochrsi_oversold_crossover),
    ("volume_spike_up", "Volume Spike Up (>=2x avg, price up)", _detect_volume_spike_up),
    ("cpr_breakout", "CPR Breakout (cross above TC)", _detect_cpr_above),
    ("ema_20_50_cross", "EMA 20/50 Bullish Crossover", _detect_ema_20_50_crossover),
    ("mfi_oversold", "MFI Oversold (crosses below 20)", _detect_mfi_oversold),
    ("mfi_strong_inflow", "MFI Strong Inflow (crosses above 60)", _detect_mfi_strong_inflow),
    ("cmf_accumulation", "CMF Accumulation (crosses +0.05)", _detect_cmf_accumulation),
    ("cmf_strong_accum", "CMF Strong Accumulation (crosses +0.15)", _detect_cmf_strong_accumulation),
    ("obv_bull_divergence", "OBV Bullish Divergence (price down, OBV up)", _detect_obv_bullish_divergence),
    ("quiet_accumulation", "Quiet Accumulation (vol up, price tight)", _detect_quiet_accumulation),
    # ── World-class strategies ───────────────────────────────────
    ("vwap_reclaim", "VWAP Reclaim (institutional buy)", _detect_vwap_reclaim),
    ("ttm_squeeze_fire", "TTM Squeeze Fire Up (Carter)", _detect_ttm_squeeze_fire),
    ("ichimoku_tk_cloud", "Ichimoku TK Cross Above Cloud", _detect_ichimoku_bullish),
    ("vcp_breakout", "Minervini VCP Breakout", _detect_vcp_breakout),
    ("rs_breakout", "Relative Strength Breakout vs Nifty", _detect_rs_breakout),
]


def _fetch_benchmark(lookback_days: int) -> Optional[pd.DataFrame]:
    """Fetch Nifty 50 index data as benchmark for relative strength."""
    try:
        yf = __import__('yfinance')
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=lookback_days)
        data = yf.download(NIFTY50_SYMBOL, start=start.strftime("%Y-%m-%d"),
                           end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        if data is not None and not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            logger.info(f"Benchmark: Fetched {len(data)} days of Nifty 50 data")
            return data
    except Exception as e:
        logger.warning(f"Could not fetch benchmark data: {e}")
    return None


def run_backtest(tickers: List[str] = None,
                 lookback_days: int = 365) -> List[IndicatorBacktest]:
    """Run backtest for all indicators across all tickers.

    Args:
        tickers: List of tickers. Defaults to NIFTY_100.
        lookback_days: Days of historical data to use.

    Returns:
        List of IndicatorBacktest results, one per indicator.
    """
    if tickers is None:
        tickers = NIFTY_100

    # Initialize results
    results = {key: IndicatorBacktest(indicator=key, signal_name=name)
               for key, name, _ in SIGNAL_REGISTRY}

    logger.info(f"Backtest: loading data for {len(tickers)} tickers...")

    # Fetch benchmark for relative strength
    benchmark_df = _fetch_benchmark(lookback_days)

    # Fetch all data first
    all_data: Dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        logger.info(f"[{i+1}/{len(tickers)}] Fetching {ticker}...")
        try:
            df = fetch_daily_ohlcv(ticker, days=lookback_days)
            if df is not None and len(df) >= 50:
                df = compute_all_indicators(df, benchmark_df=benchmark_df)
                all_data[ticker] = df
        except Exception as e:
            logger.error(f"Failed {ticker}: {e}")
        if i < len(tickers) - 1:
            time.sleep(0.3 + random.uniform(0, 0.2))

    logger.info(f"Backtest: data loaded for {len(all_data)} stocks. Running signals...")

    # Test each indicator
    for key, name, detector in SIGNAL_REGISTRY:
        bt = results[key]
        stocks_hit = 0

        for ticker, df in all_data.items():
            # Only test signals in the first ~80% of data so we have
            # forward returns to measure (need at least 20 days ahead)
            max_signal_idx = len(df) - 21  # need 20 days forward
            if max_signal_idx < 50:
                continue

            signal_indices = detector(df)
            # Filter to valid range
            signal_indices = [idx for idx in signal_indices if idx <= max_signal_idx]

            if signal_indices:
                stocks_hit += 1

            for idx in signal_indices:
                trade = _compute_forward_returns(df, idx, ticker)
                bt.trades.append(trade)

        bt.total_signals = len(bt.trades)
        bt.stocks_with_signals = stocks_hit
        bt.compute_stats()

        logger.info(f"  {name}: {bt.total_signals} signals across {stocks_hit} stocks | "
                    f"Win 5D: {bt.win_rate_5d}% | Win 10D: {bt.win_rate_10d}% | "
                    f"Win 20D: {bt.win_rate_20d}%")

    return list(results.values())


def format_backtest_report(results: List[IndicatorBacktest]) -> str:
    """Format backtest results as a readable report."""
    lines = []
    lines.append("=" * 90)
    lines.append("  SINGLE-INDICATOR BACKTEST — Nifty 100 (1-year lookback)")
    lines.append("=" * 90)
    lines.append("")

    # Summary table
    header = (f"{'Indicator':<40} {'Signals':>7} {'Stocks':>6} "
              f"{'Win5D':>6} {'Win10D':>7} {'Win20D':>7} "
              f"{'Avg20D':>7} {'Med20D':>7} {'PF20D':>6} {'AvgDD':>7}")
    lines.append(header)
    lines.append("-" * 110)

    # Sort by 20D win rate descending
    sorted_results = sorted(results, key=lambda r: r.win_rate_20d or 0, reverse=True)

    for r in sorted_results:
        wr5 = f"{r.win_rate_5d:.0f}%" if r.win_rate_5d is not None else "N/A"
        wr10 = f"{r.win_rate_10d:.0f}%" if r.win_rate_10d is not None else "N/A"
        wr20 = f"{r.win_rate_20d:.0f}%" if r.win_rate_20d is not None else "N/A"
        avg20 = f"{r.avg_return_20d:+.1f}%" if r.avg_return_20d is not None else "N/A"
        med20 = f"{r.median_return_20d:+.1f}%" if r.median_return_20d is not None else "N/A"
        pf = f"{r.profit_factor_20d:.1f}" if r.profit_factor_20d is not None else "N/A"
        dd = f"{r.avg_max_drawdown:.1f}%" if r.avg_max_drawdown is not None else "N/A"

        lines.append(f"{r.signal_name:<40} {r.total_signals:>7} {r.stocks_with_signals:>6} "
                     f"{wr5:>6} {wr10:>7} {wr20:>7} "
                     f"{avg20:>7} {med20:>7} {pf:>6} {dd:>7}")

    lines.append("")
    lines.append("Legend:")
    lines.append("  Win5D/10D/20D = % of trades profitable at 5/10/20 trading days")
    lines.append("  Avg20D = Average return at 20 days")
    lines.append("  Med20D = Median return at 20 days (robust to outliers)")
    lines.append("  PF20D  = Profit Factor at 20 days (gross profit / gross loss, >1 = profitable)")
    lines.append("  AvgDD  = Average max intra-trade drawdown (worst dip within 20 days)")
    lines.append("")

    return "\n".join(lines)


def backtest_to_json(results: List[IndicatorBacktest]) -> List[dict]:
    """Convert backtest results to JSON-serializable format for dashboard."""
    output = []
    for r in results:
        output.append({
            "indicator": r.indicator,
            "signal_name": r.signal_name,
            "total_signals": r.total_signals,
            "stocks_with_signals": r.stocks_with_signals,
            "win_rate_5d": r.win_rate_5d,
            "win_rate_10d": r.win_rate_10d,
            "win_rate_20d": r.win_rate_20d,
            "avg_return_5d": r.avg_return_5d,
            "avg_return_10d": r.avg_return_10d,
            "avg_return_20d": r.avg_return_20d,
            "median_return_5d": r.median_return_5d,
            "median_return_10d": r.median_return_10d,
            "median_return_20d": r.median_return_20d,
            "avg_max_drawdown": r.avg_max_drawdown,
            "profit_factor_20d": r.profit_factor_20d,
        })
    return output


# ═══════════════════════════════════════════════════════════════
# PAIRWISE COMBINATION BACKTESTER
# ═══════════════════════════════════════════════════════════════

# Indicators to test in pairs
PAIR_INDICATORS = [
    ("rsi_oversold", "RSI Oversold", _detect_rsi_oversold),
    ("bb_lower_touch", "BB Lower Touch", _detect_bollinger_lower_touch),
    ("stochrsi_crossover", "StochRSI Cross", _detect_stochrsi_oversold_crossover),
    ("macd_crossover", "MACD Cross", _detect_macd_bullish_crossover),
    ("ema_20_50_cross", "EMA 20/50 Cross", _detect_ema_20_50_crossover),
]


def _find_confluence_signals(indices_a: List[int], indices_b: List[int],
                              window: int = 3) -> List[int]:
    """Find dates where both signals fire within `window` trading days.

    Returns the later of the two signal dates (entry point after both confirm).
    De-duplicates to avoid overlapping entries.
    """
    if not indices_a or not indices_b:
        return []

    set_b = set(indices_b)
    confluences = []
    last_entry = -window - 1  # prevent overlapping trades

    for idx_a in indices_a:
        # Check if any signal B fires within [idx_a - window, idx_a + window]
        for offset in range(-window, window + 1):
            check_idx = idx_a + offset
            if check_idx in set_b:
                # Entry at the later of the two signals
                entry = max(idx_a, check_idx)
                if entry - last_entry > window:  # avoid overlapping trades
                    confluences.append(entry)
                    last_entry = entry
                break

    return confluences


def run_pairwise_backtest(tickers: List[str] = None,
                          lookback_days: int = 365,
                          confluence_window: int = 3,
                          all_data: Dict[str, pd.DataFrame] = None) -> Tuple[List[IndicatorBacktest], List[IndicatorBacktest]]:
    """Run pairwise combination backtest.

    Args:
        tickers: List of tickers. Defaults to NIFTY_100.
        lookback_days: Days of historical data.
        confluence_window: Max days between two signals to count as confluence.
        all_data: Pre-fetched data dict. If None, fetches fresh.

    Returns:
        Tuple of (single_results, pair_results) for comparison.
    """
    from itertools import combinations

    if tickers is None:
        tickers = NIFTY_100

    # Fetch data if not provided
    if all_data is None:
        all_data = {}
        benchmark_df = _fetch_benchmark(lookback_days)
        logger.info(f"Pairwise backtest: loading data for {len(tickers)} tickers...")
        for i, ticker in enumerate(tickers):
            logger.info(f"[{i+1}/{len(tickers)}] Fetching {ticker}...")
            try:
                df = fetch_daily_ohlcv(ticker, days=lookback_days)
                if df is not None and len(df) >= 50:
                    df = compute_all_indicators(df, benchmark_df=benchmark_df)
                    all_data[ticker] = df
            except Exception as e:
                logger.error(f"Failed {ticker}: {e}")
            if i < len(tickers) - 1:
                time.sleep(0.3 + random.uniform(0, 0.2))

    logger.info(f"Pairwise backtest: data for {len(all_data)} stocks. "
                f"Testing {len(PAIR_INDICATORS)} singles + "
                f"{len(list(combinations(PAIR_INDICATORS, 2)))} pairs...")

    # ── Singles first (for comparison) ──────────────────────────────
    single_results = []
    for key, name, detector in PAIR_INDICATORS:
        bt = IndicatorBacktest(indicator=key, signal_name=name)
        stocks_hit = 0

        for ticker, df in all_data.items():
            max_signal_idx = len(df) - 21
            if max_signal_idx < 50:
                continue

            signal_indices = detector(df)
            signal_indices = [idx for idx in signal_indices if idx <= max_signal_idx]

            if signal_indices:
                stocks_hit += 1
            for idx in signal_indices:
                trade = _compute_forward_returns(df, idx, ticker)
                bt.trades.append(trade)

        bt.total_signals = len(bt.trades)
        bt.stocks_with_signals = stocks_hit
        bt.compute_stats()
        single_results.append(bt)

        logger.info(f"  [Single] {name}: {bt.total_signals} signals | "
                    f"Win20D: {bt.win_rate_20d}% | Avg: {bt.avg_return_20d}%")

    # ── Pairwise combinations ──────────────────────────────────────
    pair_results = []
    for (key_a, name_a, det_a), (key_b, name_b, det_b) in combinations(PAIR_INDICATORS, 2):
        pair_key = f"{key_a}+{key_b}"
        pair_name = f"{name_a} + {name_b}"
        bt = IndicatorBacktest(indicator=pair_key, signal_name=pair_name)
        stocks_hit = 0

        for ticker, df in all_data.items():
            max_signal_idx = len(df) - 21
            if max_signal_idx < 50:
                continue

            signals_a = det_a(df)
            signals_b = det_b(df)

            confluence = _find_confluence_signals(signals_a, signals_b,
                                                  window=confluence_window)
            confluence = [idx for idx in confluence if idx <= max_signal_idx]

            if confluence:
                stocks_hit += 1
            for idx in confluence:
                trade = _compute_forward_returns(df, idx, ticker)
                bt.trades.append(trade)

        bt.total_signals = len(bt.trades)
        bt.stocks_with_signals = stocks_hit
        bt.compute_stats()
        pair_results.append(bt)

        logger.info(f"  [Pair] {pair_name}: {bt.total_signals} signals | "
                    f"Win20D: {bt.win_rate_20d}% | Avg: {bt.avg_return_20d}%")

    return single_results, pair_results


def format_pairwise_report(single_results: List[IndicatorBacktest],
                           pair_results: List[IndicatorBacktest],
                           confluence_window: int = 3) -> str:
    """Format pairwise backtest results."""
    lines = []
    lines.append("=" * 120)
    lines.append("  PAIRWISE COMBINATION BACKTEST — Nifty 100 (1-year lookback)")
    lines.append(f"  Confluence window: {confluence_window} trading days")
    lines.append("=" * 120)

    # Singles for reference
    lines.append("")
    lines.append("  SINGLE INDICATORS (baseline)")
    lines.append("  " + "-" * 105)
    header = (f"  {'Indicator':<30} {'Signals':>7} {'Stocks':>6} "
              f"{'Win5D':>6} {'Win10D':>7} {'Win20D':>7} "
              f"{'Avg20D':>7} {'Med20D':>7} {'PF20D':>6} {'AvgDD':>7}")
    lines.append(header)
    lines.append("  " + "-" * 105)

    for r in sorted(single_results, key=lambda x: x.win_rate_20d or 0, reverse=True):
        lines.append(_format_result_line(r, indent="  "))

    # Pairs
    lines.append("")
    lines.append("  PAIRWISE COMBINATIONS (sorted by 20D win rate)")
    lines.append("  " + "-" * 105)
    lines.append(header)
    lines.append("  " + "-" * 105)

    sorted_pairs = sorted(pair_results, key=lambda x: x.win_rate_20d or 0, reverse=True)
    for r in sorted_pairs:
        lines.append(_format_result_line(r, indent="  "))

    # Lift analysis
    lines.append("")
    lines.append("  LIFT ANALYSIS — Does the pair beat the best single?")
    lines.append("  " + "-" * 105)
    lines.append(f"  {'Pair':<40} {'PairWR':>7} {'BestSingle':>10} {'Lift':>7} {'PairPF':>7} {'PairAvg':>8} {'Signals':>7}  Verdict")
    lines.append("  " + "-" * 105)

    # Build single lookup
    single_map = {r.indicator: r for r in single_results}

    for pr in sorted_pairs:
        keys = pr.indicator.split("+")
        best_single_wr = 0
        best_single_name = ""
        for k in keys:
            sr = single_map.get(k)
            if sr and (sr.win_rate_20d or 0) > best_single_wr:
                best_single_wr = sr.win_rate_20d or 0
                best_single_name = sr.signal_name

        pair_wr = pr.win_rate_20d or 0
        lift = pair_wr - best_single_wr
        pair_pf = pr.profit_factor_20d
        pair_avg = pr.avg_return_20d

        if pr.total_signals < 5:
            verdict = "Too few signals"
        elif lift >= 10 and pair_pf and pair_pf >= 1.5:
            verdict = "STRONG COMBO"
        elif lift >= 5 and pair_pf and pair_pf >= 1.2:
            verdict = "GOOD COMBO"
        elif lift >= 0:
            verdict = "Marginal"
        else:
            verdict = "No improvement"

        pf_str = f"{pair_pf:.1f}" if pair_pf is not None else "N/A"
        avg_str = f"{pair_avg:+.1f}%" if pair_avg is not None else "N/A"

        lines.append(f"  {pr.signal_name:<40} {pair_wr:>6.0f}% {best_single_wr:>9.0f}% "
                     f"{lift:>+6.1f}% {pf_str:>7} {avg_str:>8} {pr.total_signals:>7}  {verdict}")

    lines.append("")
    lines.append("  Legend:")
    lines.append("    Lift = Pair Win Rate - Best Single Component Win Rate")
    lines.append("    STRONG COMBO = Lift >= 10% AND Profit Factor >= 1.5")
    lines.append("    GOOD COMBO   = Lift >= 5% AND Profit Factor >= 1.2")
    lines.append(f"    Confluence window = {confluence_window} trading days (both signals must fire within this window)")
    lines.append("")

    return "\n".join(lines)


def _format_result_line(r: IndicatorBacktest, indent: str = "") -> str:
    wr5 = f"{r.win_rate_5d:.0f}%" if r.win_rate_5d is not None else "N/A"
    wr10 = f"{r.win_rate_10d:.0f}%" if r.win_rate_10d is not None else "N/A"
    wr20 = f"{r.win_rate_20d:.0f}%" if r.win_rate_20d is not None else "N/A"
    avg20 = f"{r.avg_return_20d:+.1f}%" if r.avg_return_20d is not None else "N/A"
    med20 = f"{r.median_return_20d:+.1f}%" if r.median_return_20d is not None else "N/A"
    pf = f"{r.profit_factor_20d:.1f}" if r.profit_factor_20d is not None else "N/A"
    dd = f"{r.avg_max_drawdown:.1f}%" if r.avg_max_drawdown is not None else "N/A"

    return (f"{indent}{r.signal_name:<30} {r.total_signals:>7} {r.stocks_with_signals:>6} "
            f"{wr5:>6} {wr10:>7} {wr20:>7} "
            f"{avg20:>7} {med20:>7} {pf:>6} {dd:>7}")
