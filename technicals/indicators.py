"""Technical indicators — RSI, MACD, CPR, Volume analysis.

All functions take a pandas DataFrame with OHLCV columns and return
the DataFrame with new indicator columns appended.
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional


# ═══════════════════════════════════════════════════════════════
# RSI — Relative Strength Index
# ═══════════════════════════════════════════════════════════════

def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add RSI column. Uses Wilder's smoothing (exponential moving average).

    RSI = 100 - 100 / (1 + RS)
    RS = avg_gain / avg_loss over `period` days
    """
    delta = df["Close"].diff()

    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Wilder's smoothing: EMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def rsi_signal(rsi_value: float) -> str:
    """Interpret RSI value.

    Returns: 'oversold', 'overbought', or 'neutral'
    """
    if rsi_value is None or np.isnan(rsi_value):
        return "neutral"
    if rsi_value <= 30:
        return "oversold"
    if rsi_value >= 70:
        return "overbought"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# MACD — Moving Average Convergence Divergence
# ═══════════════════════════════════════════════════════════════

def compute_macd(df: pd.DataFrame,
                  fast: int = 12, slow: int = 26,
                  signal: int = 9) -> pd.DataFrame:
    """Add MACD, MACD_Signal, and MACD_Histogram columns.

    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(signal) of MACD Line
    Histogram = MACD Line - Signal Line
    """
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()

    df["MACD"] = ema_fast - ema_slow
    df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_Histogram"] = df["MACD"] - df["MACD_Signal"]
    return df


def macd_signal(df: pd.DataFrame) -> str:
    """Detect MACD crossover from the last 2 bars.

    Returns: 'bullish_crossover', 'bearish_crossover', 'bullish', 'bearish', 'neutral'
    """
    if len(df) < 2 or "MACD" not in df.columns:
        return "neutral"

    hist_now = df["MACD_Histogram"].iloc[-1]
    hist_prev = df["MACD_Histogram"].iloc[-2]

    if pd.isna(hist_now) or pd.isna(hist_prev):
        return "neutral"

    # Crossover detection
    if hist_prev <= 0 and hist_now > 0:
        return "bullish_crossover"
    if hist_prev >= 0 and hist_now < 0:
        return "bearish_crossover"
    if hist_now > 0:
        return "bullish"
    if hist_now < 0:
        return "bearish"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# CPR — Central Pivot Range
# ═══════════════════════════════════════════════════════════════

def compute_cpr(df: pd.DataFrame) -> pd.DataFrame:
    """Add CPR columns: Pivot, TC (Top Central), BC (Bottom Central).

    Uses PREVIOUS day's OHLC to calculate today's pivot levels.

    Central Pivot (P) = (High + Low + Close) / 3
    Bottom Central (BC) = (High + Low) / 2
    Top Central (TC) = (P - BC) + P = 2*P - BC
    """
    # Shift by 1 to use previous day's values for today's levels
    prev_high = df["High"].shift(1)
    prev_low = df["Low"].shift(1)
    prev_close = df["Close"].shift(1)

    df["CPR_Pivot"] = (prev_high + prev_low + prev_close) / 3
    df["CPR_BC"] = (prev_high + prev_low) / 2
    df["CPR_TC"] = 2 * df["CPR_Pivot"] - df["CPR_BC"]

    # CPR Width as % of pivot (narrow = consolidation, wide = trending)
    df["CPR_Width_Pct"] = abs(df["CPR_TC"] - df["CPR_BC"]) / df["CPR_Pivot"] * 100

    # Support and Resistance levels (standard pivots)
    df["CPR_S1"] = 2 * df["CPR_Pivot"] - prev_high
    df["CPR_R1"] = 2 * df["CPR_Pivot"] - prev_low
    df["CPR_S2"] = df["CPR_Pivot"] - (prev_high - prev_low)
    df["CPR_R2"] = df["CPR_Pivot"] + (prev_high - prev_low)

    return df


def cpr_signal(df: pd.DataFrame) -> str:
    """Interpret current price vs CPR levels.

    Returns: 'above_cpr', 'below_cpr', 'within_cpr', 'narrow_range'
    """
    if len(df) < 2 or "CPR_Pivot" not in df.columns:
        return "neutral"

    row = df.iloc[-1]
    close = row["Close"]
    tc = row.get("CPR_TC")
    bc = row.get("CPR_BC")
    width = row.get("CPR_Width_Pct")

    if pd.isna(close) or pd.isna(tc) or pd.isna(bc):
        return "neutral"

    # Narrow CPR (< 0.5%) signals potential breakout
    if width is not None and not pd.isna(width) and width < 0.5:
        return "narrow_range"

    if close > tc:
        return "above_cpr"
    elif close < bc:
        return "below_cpr"
    else:
        return "within_cpr"


# ═══════════════════════════════════════════════════════════════
# VOLUME ANALYSIS
# ═══════════════════════════════════════════════════════════════

def compute_volume_indicators(df: pd.DataFrame,
                               sma_period: int = 20) -> pd.DataFrame:
    """Add volume analysis columns.

    - Volume_SMA: 20-day simple moving average of volume
    - Volume_Ratio: current volume / SMA (>1.5 = spike)
    - OBV: On-Balance Volume (accumulation/distribution proxy)
    """
    df["Volume_SMA"] = df["Volume"].rolling(window=sma_period).mean()
    df["Volume_Ratio"] = df["Volume"] / df["Volume_SMA"].replace(0, np.nan)

    # OBV
    obv = [0]
    for i in range(1, len(df)):
        if df["Close"].iloc[i] > df["Close"].iloc[i - 1]:
            obv.append(obv[-1] + df["Volume"].iloc[i])
        elif df["Close"].iloc[i] < df["Close"].iloc[i - 1]:
            obv.append(obv[-1] - df["Volume"].iloc[i])
        else:
            obv.append(obv[-1])
    df["OBV"] = obv

    # OBV SMA for trend detection
    df["OBV_SMA_20"] = df["OBV"].rolling(window=20).mean()

    return df


def compute_money_flow_index(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add Money Flow Index (MFI) — volume-weighted RSI.

    MFI uses both price AND volume to measure buying/selling pressure.
    MFI > 80 = overbought (money flowing in heavily)
    MFI < 20 = oversold (money flowing out)
    Rising MFI + Rising Price = strong institutional buying
    """
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    raw_money_flow = typical_price * df["Volume"]

    # Positive/negative flow based on typical price direction
    tp_diff = typical_price.diff()
    pos_flow = pd.Series(np.where(tp_diff > 0, raw_money_flow, 0),
                          index=df.index, dtype=float)
    neg_flow = pd.Series(np.where(tp_diff < 0, raw_money_flow, 0),
                          index=df.index, dtype=float)

    pos_sum = pos_flow.rolling(window=period).sum()
    neg_sum = neg_flow.rolling(window=period).sum()

    money_ratio = pos_sum / neg_sum.replace(0, np.nan)
    df["MFI"] = 100 - (100 / (1 + money_ratio))

    return df


def compute_chaikin_money_flow(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Add Chaikin Money Flow (CMF) — measures accumulation/distribution pressure.

    CMF = sum(Money Flow Volume) / sum(Volume) over period
    Range: -1 to +1
    CMF > 0 = net buying pressure (accumulation)
    CMF < 0 = net selling pressure (distribution)
    CMF > 0.1 = strong accumulation
    CMF < -0.1 = strong distribution
    """
    high_low = (df["High"] - df["Low"]).replace(0, np.nan)
    clv = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / high_low
    mf_volume = clv * df["Volume"]

    df["CMF"] = mf_volume.rolling(window=period).sum() / df["Volume"].rolling(window=period).sum()

    return df


def compute_accumulation_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Add Accumulation/Distribution Line.

    Similar to OBV but weights by where price closes within the bar.
    Close near high = accumulation, close near low = distribution.
    """
    high_low = (df["High"] - df["Low"]).replace(0, np.nan)
    clv = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / high_low
    ad_volume = clv.fillna(0) * df["Volume"]
    df["AD_Line"] = ad_volume.cumsum()
    df["AD_SMA_20"] = df["AD_Line"].rolling(window=20).mean()

    return df


def volume_signal(df: pd.DataFrame) -> str:
    """Interpret volume pattern.

    Returns: 'high_volume_up', 'high_volume_down', 'volume_spike',
             'volume_dry', 'normal'
    """
    if len(df) < 2 or "Volume_Ratio" not in df.columns:
        return "normal"

    row = df.iloc[-1]
    vol_ratio = row.get("Volume_Ratio")
    price_change = row["Close"] - df["Close"].iloc[-2]

    if pd.isna(vol_ratio):
        return "normal"

    if vol_ratio >= 2.0:
        return "high_volume_up" if price_change > 0 else "high_volume_down"
    elif vol_ratio >= 1.5:
        return "volume_spike"
    elif vol_ratio <= 0.5:
        return "volume_dry"
    return "normal"


# ═══════════════════════════════════════════════════════════════
# MOVING AVERAGES (for trend context)
# ═══════════════════════════════════════════════════════════════

def compute_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Add key moving averages: 20, 50, 200 day SMA and EMA."""
    for period in [20, 50, 200]:
        df[f"SMA_{period}"] = df["Close"].rolling(window=period).mean()
        df[f"EMA_{period}"] = df["Close"].ewm(span=period, adjust=False).mean()
    return df


def ma_trend(df: pd.DataFrame) -> str:
    """Determine trend from moving average alignment.

    Returns: 'strong_uptrend', 'uptrend', 'downtrend', 'strong_downtrend', 'sideways'
    """
    if len(df) < 200 or "SMA_200" not in df.columns:
        if len(df) >= 50 and "SMA_50" in df.columns:
            close = df["Close"].iloc[-1]
            sma50 = df["SMA_50"].iloc[-1]
            if pd.isna(sma50):
                return "sideways"
            return "uptrend" if close > sma50 else "downtrend"
        return "sideways"

    close = df["Close"].iloc[-1]
    sma20 = df["SMA_20"].iloc[-1]
    sma50 = df["SMA_50"].iloc[-1]
    sma200 = df["SMA_200"].iloc[-1]

    if any(pd.isna(v) for v in [sma20, sma50, sma200]):
        return "sideways"

    if close > sma20 > sma50 > sma200:
        return "strong_uptrend"
    elif close > sma50 > sma200:
        return "uptrend"
    elif close < sma20 < sma50 < sma200:
        return "strong_downtrend"
    elif close < sma50 < sma200:
        return "downtrend"
    return "sideways"


def ema_crossover_signal(df: pd.DataFrame) -> str:
    """Detect EMA 20/50 crossover from the last 2 bars.

    Returns: 'bullish_crossover', 'bearish_crossover', 'bullish', 'bearish', 'neutral'
    """
    if len(df) < 2 or "EMA_20" not in df.columns or "EMA_50" not in df.columns:
        return "neutral"

    ema20_now = df["EMA_20"].iloc[-1]
    ema50_now = df["EMA_50"].iloc[-1]
    ema20_prev = df["EMA_20"].iloc[-2]
    ema50_prev = df["EMA_50"].iloc[-2]

    if any(pd.isna(v) for v in [ema20_now, ema50_now, ema20_prev, ema50_prev]):
        return "neutral"

    if ema20_prev <= ema50_prev and ema20_now > ema50_now:
        return "bullish_crossover"
    elif ema20_prev >= ema50_prev and ema20_now < ema50_now:
        return "bearish_crossover"
    elif ema20_now > ema50_now:
        return "bullish"
    elif ema20_now < ema50_now:
        return "bearish"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# ADX — Average Directional Index (trend strength)
# ═══════════════════════════════════════════════════════════════

def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Add ADX, +DI, -DI columns. ADX measures trend strength (not direction).

    ADX > 25 = trending market, ADX < 20 = ranging/choppy.
    +DI > -DI = bullish trend, -DI > +DI = bearish trend.
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder's smoothing
    atr = pd.Series(tr, index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    df["ADX"] = adx
    df["Plus_DI"] = plus_di
    df["Minus_DI"] = minus_di
    return df


def adx_signal(df: pd.DataFrame) -> str:
    """Interpret ADX for trend strength + direction.

    Returns: 'strong_trend_up', 'strong_trend_down', 'trending_up', 'trending_down',
             'weak_trend', 'no_trend'
    """
    if "ADX" not in df.columns or len(df) < 2:
        return "no_trend"

    row = df.iloc[-1]
    adx = row.get("ADX")
    plus_di = row.get("Plus_DI")
    minus_di = row.get("Minus_DI")

    if any(pd.isna(v) for v in [adx, plus_di, minus_di]):
        return "no_trend"

    direction = "up" if plus_di > minus_di else "down"

    if adx >= 40:
        return f"strong_trend_{direction}"
    elif adx >= 25:
        return f"trending_{direction}"
    elif adx >= 20:
        return "weak_trend"
    return "no_trend"


# ═══════════════════════════════════════════════════════════════
# BOLLINGER BANDS
# ═══════════════════════════════════════════════════════════════

def compute_bollinger_bands(df: pd.DataFrame, period: int = 20,
                             std_dev: float = 2.0) -> pd.DataFrame:
    """Add Bollinger Band columns: BB_Mid, BB_Upper, BB_Lower, BB_Width, BB_PctB.

    BB_PctB (Percent B): 0 = at lower band, 1 = at upper band, <0 = below lower, >1 = above upper.
    BB_Width: Band width as % of middle band (squeeze detection).
    """
    df["BB_Mid"] = df["Close"].rolling(window=period).mean()
    rolling_std = df["Close"].rolling(window=period).std()

    df["BB_Upper"] = df["BB_Mid"] + std_dev * rolling_std
    df["BB_Lower"] = df["BB_Mid"] - std_dev * rolling_std
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"].replace(0, np.nan) * 100
    df["BB_PctB"] = (df["Close"] - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"]).replace(0, np.nan)

    return df


def bollinger_signal(df: pd.DataFrame) -> str:
    """Interpret Bollinger Band position.

    Returns: 'squeeze', 'lower_band_touch', 'upper_band_touch',
             'walking_upper', 'walking_lower', 'mid_band', 'neutral'
    """
    if "BB_PctB" not in df.columns or len(df) < 5:
        return "neutral"

    row = df.iloc[-1]
    pctb = row.get("BB_PctB")
    width = row.get("BB_Width")

    if pd.isna(pctb) or pd.isna(width):
        return "neutral"

    # Squeeze: width in bottom 20th percentile of recent 120 days
    recent_width = df["BB_Width"].dropna().tail(120)
    if len(recent_width) >= 20:
        width_pctile = (recent_width < width).sum() / len(recent_width)
        if width_pctile < 0.2:
            return "squeeze"

    # Band walk detection (3+ consecutive days near band)
    recent_pctb = df["BB_PctB"].dropna().tail(3)
    if len(recent_pctb) == 3:
        if all(v > 0.8 for v in recent_pctb):
            return "walking_upper"
        if all(v < 0.2 for v in recent_pctb):
            return "walking_lower"

    if pctb <= 0.0:
        return "lower_band_touch"
    elif pctb >= 1.0:
        return "upper_band_touch"
    elif 0.4 <= pctb <= 0.6:
        return "mid_band"

    return "neutral"


# ═══════════════════════════════════════════════════════════════
# SUPERTREND
# ═══════════════════════════════════════════════════════════════

def compute_supertrend(df: pd.DataFrame, period: int = 10,
                        multiplier: float = 3.0) -> pd.DataFrame:
    """Add SuperTrend and SuperTrend_Direction columns.

    SuperTrend_Direction: 1 = bullish (price above), -1 = bearish (price below).
    """
    n = len(df)
    high = df["High"].values.copy()
    low = df["Low"].values.copy()
    close = df["Close"].values.copy()

    # True Range
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i-1]),
                    abs(low[i] - close[i-1]))

    # ATR via Wilder's smoothing
    atr = np.full(n, np.nan)
    if n > period:
        atr[period] = np.mean(tr[1:period+1])
        for i in range(period + 1, n):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)

    # Find first valid index (where ATR is not NaN)
    first_valid = period
    if first_valid >= n:
        df["SuperTrend"] = np.nan
        df["SuperTrend_Direction"] = 0
        return df

    # Initialize at first valid bar
    if close[first_valid] > upper_band[first_valid]:
        direction[first_valid] = 1
        supertrend[first_valid] = lower_band[first_valid]
    else:
        direction[first_valid] = -1
        supertrend[first_valid] = upper_band[first_valid]

    for i in range(first_valid + 1, n):
        if np.isnan(atr[i]):
            direction[i] = direction[i-1]
            supertrend[i] = supertrend[i-1]
            continue

        # Adjust lower band: only allow it to rise (ratchet up during uptrend)
        if not np.isnan(lower_band[i-1]):
            if lower_band[i] < lower_band[i-1] and close[i-1] >= lower_band[i-1]:
                lower_band[i] = lower_band[i-1]

        # Adjust upper band: only allow it to fall (ratchet down during downtrend)
        if not np.isnan(upper_band[i-1]):
            if upper_band[i] > upper_band[i-1] and close[i-1] <= upper_band[i-1]:
                upper_band[i] = upper_band[i-1]

        if direction[i-1] == 1:  # was bullish
            if close[i] < lower_band[i]:
                direction[i] = -1
                supertrend[i] = upper_band[i]
            else:
                direction[i] = 1
                supertrend[i] = lower_band[i]
        else:  # was bearish
            if close[i] > upper_band[i]:
                direction[i] = 1
                supertrend[i] = lower_band[i]
            else:
                direction[i] = -1
                supertrend[i] = upper_band[i]

    df["SuperTrend"] = supertrend
    df["SuperTrend_Direction"] = direction
    return df


def supertrend_signal(df: pd.DataFrame) -> str:
    """Interpret SuperTrend.

    Returns: 'bullish_flip', 'bearish_flip', 'bullish', 'bearish', 'neutral'
    """
    if "SuperTrend_Direction" not in df.columns or len(df) < 2:
        return "neutral"

    curr = df["SuperTrend_Direction"].iloc[-1]
    prev = df["SuperTrend_Direction"].iloc[-2]

    if curr == 0 or prev == 0:
        return "neutral"

    if prev == -1 and curr == 1:
        return "bullish_flip"
    elif prev == 1 and curr == -1:
        return "bearish_flip"
    elif curr == 1:
        return "bullish"
    elif curr == -1:
        return "bearish"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# STOCHASTIC RSI
# ═══════════════════════════════════════════════════════════════

def compute_stochastic_rsi(df: pd.DataFrame, rsi_period: int = 14,
                            stoch_period: int = 14,
                            k_period: int = 3,
                            d_period: int = 3) -> pd.DataFrame:
    """Add StochRSI_K and StochRSI_D columns (0-100 scale).

    StochRSI applies Stochastic oscillator formula to RSI values.
    Faster than plain RSI at detecting momentum shifts.
    """
    if "RSI" not in df.columns:
        df = compute_rsi(df, period=rsi_period)

    rsi = df["RSI"]
    rsi_min = rsi.rolling(window=stoch_period).min()
    rsi_max = rsi.rolling(window=stoch_period).max()

    stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan) * 100

    df["StochRSI_K"] = stoch_rsi.rolling(window=k_period).mean()
    df["StochRSI_D"] = df["StochRSI_K"].rolling(window=d_period).mean()
    return df


def stochrsi_signal(df: pd.DataFrame) -> str:
    """Interpret Stochastic RSI.

    Returns: 'oversold_crossover', 'overbought_crossover',
             'oversold', 'overbought', 'neutral'
    """
    if "StochRSI_K" not in df.columns or len(df) < 2:
        return "neutral"

    k_now = df["StochRSI_K"].iloc[-1]
    d_now = df["StochRSI_D"].iloc[-1]
    k_prev = df["StochRSI_K"].iloc[-2]
    d_prev = df["StochRSI_D"].iloc[-2]

    if any(pd.isna(v) for v in [k_now, d_now, k_prev, d_prev]):
        return "neutral"

    # Bullish crossover in oversold zone
    if k_now < 20 and k_prev <= d_prev and k_now > d_now:
        return "oversold_crossover"
    # Bearish crossover in overbought zone
    if k_now > 80 and k_prev >= d_prev and k_now < d_now:
        return "overbought_crossover"

    if k_now <= 20:
        return "oversold"
    if k_now >= 80:
        return "overbought"

    return "neutral"


# ═══════════════════════════════════════════════════════════════
# VWAP — Volume Weighted Average Price
# ═══════════════════════════════════════════════════════════════

def compute_vwap(df: pd.DataFrame, anchor_period: int = 20) -> pd.DataFrame:
    """Add rolling VWAP column (anchored to N-day rolling window).

    VWAP = cumsum(Typical Price * Volume) / cumsum(Volume)
    Institutional traders use VWAP as fair value — price above = bullish, below = bearish.
    """
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_vol = tp * df["Volume"]

    df["VWAP"] = tp_vol.rolling(window=anchor_period).sum() / df["Volume"].rolling(window=anchor_period).sum()
    return df


def vwap_signal(df: pd.DataFrame) -> str:
    """Interpret price vs VWAP.

    Returns: 'vwap_reclaim', 'above_vwap', 'below_vwap', 'neutral'
    """
    if "VWAP" not in df.columns or len(df) < 2:
        return "neutral"

    close_now = df["Close"].iloc[-1]
    close_prev = df["Close"].iloc[-2]
    vwap_now = df["VWAP"].iloc[-1]
    vwap_prev = df["VWAP"].iloc[-2]

    if any(pd.isna(v) for v in [close_now, close_prev, vwap_now, vwap_prev]):
        return "neutral"

    # Reclaim: was below VWAP, now above
    if close_prev < vwap_prev and close_now > vwap_now:
        return "vwap_reclaim"
    elif close_now > vwap_now:
        return "above_vwap"
    elif close_now < vwap_now:
        return "below_vwap"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# KELTNER CHANNELS (for TTM Squeeze detection)
# ═══════════════════════════════════════════════════════════════

def compute_keltner_channels(df: pd.DataFrame, period: int = 20,
                              atr_mult: float = 1.5) -> pd.DataFrame:
    """Add Keltner Channel columns: KC_Mid, KC_Upper, KC_Lower.

    Keltner = EMA(period) ± atr_mult * ATR(period)
    Used with Bollinger Bands for TTM Squeeze detection.
    """
    df["KC_Mid"] = df["Close"].ewm(span=period, adjust=False).mean()

    # ATR
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift(1)).abs()
    tr3 = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    df["KC_Upper"] = df["KC_Mid"] + atr_mult * atr
    df["KC_Lower"] = df["KC_Mid"] - atr_mult * atr
    df["KC_ATR"] = atr
    return df


def ttm_squeeze_signal(df: pd.DataFrame) -> str:
    """Detect TTM Squeeze: Bollinger Bands inside Keltner Channels.

    Returns: 'squeeze_fire_up', 'squeeze_fire_down', 'in_squeeze', 'no_squeeze'
    """
    if not all(c in df.columns for c in ["BB_Upper", "BB_Lower", "KC_Upper", "KC_Lower"]):
        return "no_squeeze"
    if len(df) < 3:
        return "no_squeeze"

    bb_upper = df["BB_Upper"].iloc[-1]
    bb_lower = df["BB_Lower"].iloc[-1]
    kc_upper = df["KC_Upper"].iloc[-1]
    kc_lower = df["KC_Lower"].iloc[-1]

    bb_upper_prev = df["BB_Upper"].iloc[-2]
    bb_lower_prev = df["BB_Lower"].iloc[-2]
    kc_upper_prev = df["KC_Upper"].iloc[-2]
    kc_lower_prev = df["KC_Lower"].iloc[-2]

    if any(pd.isna(v) for v in [bb_upper, bb_lower, kc_upper, kc_lower,
                                  bb_upper_prev, bb_lower_prev, kc_upper_prev, kc_lower_prev]):
        return "no_squeeze"

    in_squeeze_now = bb_lower > kc_lower and bb_upper < kc_upper
    in_squeeze_prev = bb_lower_prev > kc_lower_prev and bb_upper_prev < kc_upper_prev

    # Squeeze just fired (was in squeeze, now released)
    if in_squeeze_prev and not in_squeeze_now:
        # Direction from MACD histogram momentum
        if "MACD_Histogram" in df.columns:
            hist = df["MACD_Histogram"].iloc[-1]
            if pd.notna(hist):
                return "squeeze_fire_up" if hist > 0 else "squeeze_fire_down"
        # Fallback: use price direction
        if df["Close"].iloc[-1] > df["Close"].iloc[-2]:
            return "squeeze_fire_up"
        return "squeeze_fire_down"

    if in_squeeze_now:
        return "in_squeeze"
    return "no_squeeze"


# ═══════════════════════════════════════════════════════════════
# ICHIMOKU CLOUD
# ═══════════════════════════════════════════════════════════════

def compute_ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26,
                      senkou_b: int = 52) -> pd.DataFrame:
    """Add Ichimoku Cloud columns.

    Tenkan-sen (Conversion Line): (9-period high + low) / 2
    Kijun-sen (Base Line): (26-period high + low) / 2
    Senkou Span A: (Tenkan + Kijun) / 2, shifted 26 ahead
    Senkou Span B: (52-period high + low) / 2, shifted 26 ahead
    Chikou Span: Close shifted 26 back
    """
    high_t = df["High"].rolling(window=tenkan).max()
    low_t = df["Low"].rolling(window=tenkan).min()
    df["Ichimoku_Tenkan"] = (high_t + low_t) / 2

    high_k = df["High"].rolling(window=kijun).max()
    low_k = df["Low"].rolling(window=kijun).min()
    df["Ichimoku_Kijun"] = (high_k + low_k) / 2

    df["Ichimoku_SpanA"] = ((df["Ichimoku_Tenkan"] + df["Ichimoku_Kijun"]) / 2).shift(kijun)
    high_sb = df["High"].rolling(window=senkou_b).max()
    low_sb = df["Low"].rolling(window=senkou_b).min()
    df["Ichimoku_SpanB"] = ((high_sb + low_sb) / 2).shift(kijun)

    df["Ichimoku_Chikou"] = df["Close"].shift(-kijun)

    return df


def ichimoku_signal(df: pd.DataFrame) -> str:
    """Interpret Ichimoku Cloud for trading signals.

    Returns: 'tk_cross_above_cloud', 'bullish_above_cloud', 'bearish_below_cloud',
             'in_cloud', 'tk_cross_below_cloud', 'neutral'
    """
    if not all(c in df.columns for c in ["Ichimoku_Tenkan", "Ichimoku_Kijun",
                                           "Ichimoku_SpanA", "Ichimoku_SpanB"]):
        return "neutral"
    if len(df) < 2:
        return "neutral"

    close = df["Close"].iloc[-1]
    tenkan = df["Ichimoku_Tenkan"].iloc[-1]
    kijun = df["Ichimoku_Kijun"].iloc[-1]
    span_a = df["Ichimoku_SpanA"].iloc[-1]
    span_b = df["Ichimoku_SpanB"].iloc[-1]

    tenkan_prev = df["Ichimoku_Tenkan"].iloc[-2]
    kijun_prev = df["Ichimoku_Kijun"].iloc[-2]

    if any(pd.isna(v) for v in [close, tenkan, kijun, span_a, span_b, tenkan_prev, kijun_prev]):
        return "neutral"

    cloud_top = max(span_a, span_b)
    cloud_bottom = min(span_a, span_b)
    above_cloud = close > cloud_top
    below_cloud = close < cloud_bottom

    # TK Cross: Tenkan crosses above Kijun
    tk_cross_up = tenkan_prev <= kijun_prev and tenkan > kijun
    tk_cross_down = tenkan_prev >= kijun_prev and tenkan < kijun

    if tk_cross_up and above_cloud:
        return "tk_cross_above_cloud"
    if tk_cross_down and below_cloud:
        return "tk_cross_below_cloud"
    if above_cloud and tenkan > kijun:
        return "bullish_above_cloud"
    if below_cloud and tenkan < kijun:
        return "bearish_below_cloud"
    if cloud_bottom <= close <= cloud_top:
        return "in_cloud"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# RELATIVE STRENGTH vs INDEX
# ═══════════════════════════════════════════════════════════════

def compute_relative_strength(df: pd.DataFrame, benchmark_df: pd.DataFrame,
                               period: int = 20) -> pd.DataFrame:
    """Add Relative Strength columns comparing stock to benchmark index.

    RS_Ratio = Stock % change / Benchmark % change (rolling)
    RS_Line = cumulative ratio (stock/benchmark normalized to 100)
    RS > 1 = outperforming, RS < 1 = underperforming
    """
    if benchmark_df is None or len(benchmark_df) < period:
        df["RS_Ratio"] = np.nan
        df["RS_Line"] = np.nan
        df["RS_SMA"] = np.nan
        return df

    # Align dates
    common_idx = df.index.intersection(benchmark_df.index)
    if len(common_idx) < period:
        df["RS_Ratio"] = np.nan
        df["RS_Line"] = np.nan
        df["RS_SMA"] = np.nan
        return df

    stock_close = df["Close"].reindex(common_idx)
    bench_close = benchmark_df["Close"].reindex(common_idx)

    # RS Line: stock/benchmark, normalized
    rs_line = (stock_close / bench_close) * 100
    df["RS_Line"] = rs_line.reindex(df.index)

    # RS Ratio: rolling N-day relative return
    stock_ret = stock_close.pct_change(period)
    bench_ret = bench_close.pct_change(period)
    rs_ratio = (1 + stock_ret) / (1 + bench_ret)
    df["RS_Ratio"] = rs_ratio.reindex(df.index)

    # SMA of RS Line for trend
    df["RS_SMA"] = df["RS_Line"].rolling(window=period).mean()

    return df


def relative_strength_signal(df: pd.DataFrame) -> str:
    """Interpret relative strength vs index.

    Returns: 'rs_new_high', 'rs_improving', 'rs_declining', 'rs_new_low', 'neutral'
    """
    if "RS_Line" not in df.columns or "RS_SMA" not in df.columns:
        return "neutral"
    if len(df) < 21:
        return "neutral"

    rs_now = df["RS_Line"].iloc[-1]
    rs_sma = df["RS_SMA"].iloc[-1]

    if pd.isna(rs_now) or pd.isna(rs_sma):
        return "neutral"

    # Check if RS is at 20-day high
    rs_20d_high = df["RS_Line"].iloc[-20:].max()
    rs_20d_low = df["RS_Line"].iloc[-20:].min()

    if pd.isna(rs_20d_high):
        return "neutral"

    if rs_now >= rs_20d_high * 0.99:  # within 1% of high
        return "rs_new_high"
    elif rs_now <= rs_20d_low * 1.01:
        return "rs_new_low"
    elif rs_now > rs_sma:
        return "rs_improving"
    elif rs_now < rs_sma:
        return "rs_declining"
    return "neutral"


# ═══════════════════════════════════════════════════════════════
# MINERVINI VCP — Volatility Contraction Pattern
# ═══════════════════════════════════════════════════════════════

def compute_vcp(df: pd.DataFrame) -> pd.DataFrame:
    """Detect Minervini's Volatility Contraction Pattern.

    VCP: price makes progressively tighter consolidations (contractions)
    with declining volume before breaking out.

    Adds: VCP_Contraction (ratio of current range to prior range),
          VCP_Score (0-100, higher = stronger VCP pattern)
    """
    n = len(df)
    vcp_score = np.full(n, 0.0)
    vcp_contraction = np.full(n, np.nan)

    if n < 60:
        df["VCP_Contraction"] = vcp_contraction
        df["VCP_Score"] = vcp_score
        return df

    for i in range(60, n):
        # Check 3 contractions over ~60 days: [i-60:i-40], [i-40:i-20], [i-20:i]
        ranges = []
        for start, end in [(i-60, i-40), (i-40, i-20), (i-20, i)]:
            hi = df["High"].iloc[start:end].max()
            lo = df["Low"].iloc[start:end].min()
            mid = df["Close"].iloc[start:end].mean()
            if mid > 0:
                ranges.append((hi - lo) / mid * 100)
            else:
                ranges.append(0)

        if len(ranges) == 3 and all(r > 0 for r in ranges):
            # Check tightening: each range smaller than previous
            c1 = ranges[1] / ranges[0] if ranges[0] > 0 else 1
            c2 = ranges[2] / ranges[1] if ranges[1] > 0 else 1
            vcp_contraction[i] = c2

            score = 0

            # Contracting ranges (each tighter = +25)
            if c1 < 0.8:
                score += 25
            elif c1 < 1.0:
                score += 10
            if c2 < 0.8:
                score += 25
            elif c2 < 1.0:
                score += 10

            # Volume declining in last contraction
            vol_early = df["Volume"].iloc[i-60:i-20].mean()
            vol_late = df["Volume"].iloc[i-20:i].mean()
            if vol_early > 0 and vol_late / vol_early < 0.8:
                score += 25
            elif vol_early > 0 and vol_late / vol_early < 1.0:
                score += 10

            # Price above 50-day MA (Minervini trend template)
            if "SMA_50" in df.columns:
                sma50 = df["SMA_50"].iloc[i]
                if pd.notna(sma50) and df["Close"].iloc[i] > sma50:
                    score += 25

            vcp_score[i] = min(score, 100)

    df["VCP_Contraction"] = vcp_contraction
    df["VCP_Score"] = vcp_score
    return df


def vcp_signal(df: pd.DataFrame) -> str:
    """Interpret VCP pattern strength.

    Returns: 'vcp_breakout', 'vcp_forming', 'no_pattern'
    """
    if "VCP_Score" not in df.columns or len(df) < 2:
        return "no_pattern"

    score_now = df["VCP_Score"].iloc[-1]
    score_prev = df["VCP_Score"].iloc[-2]

    if pd.isna(score_now):
        return "no_pattern"

    # Breakout: high VCP score + price breaking above recent range
    if score_now >= 70:
        # Check if price is breaking out (above recent 20-day high)
        recent_high = df["High"].iloc[-21:-1].max()
        if pd.notna(recent_high) and df["Close"].iloc[-1] > recent_high:
            return "vcp_breakout"
        return "vcp_forming"

    if score_now >= 50:
        return "vcp_forming"

    return "no_pattern"


# ═══════════════════════════════════════════════════════════════
# COMPUTE ALL
# ═══════════════════════════════════════════════════════════════

def compute_all_indicators(df: pd.DataFrame,
                            benchmark_df: pd.DataFrame = None) -> pd.DataFrame:
    """Compute all technical indicators on a OHLCV DataFrame."""
    df = compute_rsi(df)
    df = compute_macd(df)
    df = compute_cpr(df)
    df = compute_volume_indicators(df)
    df = compute_moving_averages(df)
    df = compute_adx(df)
    df = compute_bollinger_bands(df)
    df = compute_supertrend(df)
    df = compute_stochastic_rsi(df)
    df = compute_money_flow_index(df)
    df = compute_chaikin_money_flow(df)
    df = compute_accumulation_distribution(df)
    df = compute_vwap(df)
    df = compute_keltner_channels(df)
    df = compute_ichimoku(df)
    df = compute_vcp(df)
    if benchmark_df is not None:
        df = compute_relative_strength(df, benchmark_df)
    return df
