"""Vinoth's Strategy: RSI <= 35 + MACD Convergence early entry.

Backtested edge (3Y, Nifty 100):
  - Enter when RSI <= 35 and MACD histogram is converging (becoming less negative)
  - 20-day win rate: 64.6%, avg return: +3.21%
  - 95% of the time MACD crossover follows within 15 days
  - Time-stop: exit if MACD doesn't cross within 10 days

Scans all Nifty 100 stocks and classifies them into:
  1. ENTRY ZONE  - RSI <= 35 right now, MACD converging -> act
  2. NEAR ZONE   - RSI 35-42 and falling, approaching entry -> watch
  3. CROSSED     - Was in entry zone recently, MACD just crossed -> already running
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List

import numpy as np
import pandas as pd

from dashboard.sectors import get_sector, get_industry


@dataclass
class StrategySignal:
    ticker: str
    sector: str = ""
    industry: str = ""
    date: str = ""
    close: Optional[float] = None
    change_1d: Optional[float] = None

    # RSI state
    rsi: Optional[float] = None
    rsi_low: Optional[float] = None        # lowest RSI in last 10 days
    rsi_low_date: str = ""
    days_since_rsi_low: int = 0

    # MACD state
    macd_histogram: Optional[float] = None
    macd_hist_prev: Optional[float] = None
    macd_hist_direction: str = ""           # rising, falling, flat
    macd_converging_days: int = 0           # consecutive days histogram rising while negative
    macd_crossed: bool = False              # histogram just turned positive
    days_since_cross: int = 0

    # Entry classification
    zone: str = ""                          # entry, near, crossed, none
    zone_label: str = ""

    # Backtest context
    historical_win_rate: Optional[float] = None   # stock-specific 20D win rate
    historical_avg_return: Optional[float] = None  # stock-specific 20D avg return
    historical_trades: int = 0

    # Trade levels (ATR-based)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    sl_pct: Optional[float] = None
    target_10d: Optional[float] = None
    target_20d: Optional[float] = None
    atr: Optional[float] = None

    # Risk flags
    risk_flags: List[str] = field(default_factory=list)


def _safe(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


def _compute_rsi(df, period=14):
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _compute_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


# Stock-specific backtest stats (from 3Y backtest)
# Only stocks with 2+ historical trades included
STOCK_STATS = {
    'HINDALCO': (100, 8.93, 2), 'MOTHERSON': (100, 11.06, 3),
    'SIEMENS': (100, 6.28, 2), 'BHEL': (100, 6.19, 2),
    'GRASIM': (100, 5.00, 4), 'ULTRACEMCO': (100, 7.33, 3),
    'MARICO': (100, 5.49, 2), 'BEL': (100, 5.07, 3),
    'IOC': (100, 4.18, 3), 'DRREDDY': (100, 4.05, 3),
    'EICHERMOT': (100, 5.55, 2), 'SUNPHARMA': (100, 2.85, 3),
    'NTPC': (100, 2.50, 2), 'INFY': (100, 2.77, 2),
    'PERSISTENT': (80, 5.91, 5), 'ADANIPORTS': (75, 8.42, 4),
    'ASIANPAINT': (75, 8.65, 4), 'NESTLEIND': (75, 7.30, 4),
    'HAL': (75, 8.36, 4), 'MUTHOOTFIN': (75, 3.41, 4),
    'HINDUNILVR': (75, 4.00, 4), 'RECLTD': (75, 3.38, 4),
    'GODREJCP': (75, 0.21, 4), 'TECHM': (75, 3.48, 4),
    'NHPC': (75, 5.10, 4), 'BAJAJFINSV': (75, 1.99, 4),
    'UPL': (75, 0.02, 4), 'HCLTECH': (75, 2.64, 4),
    'LICI': (75, 2.08, 4), 'TITAN': (75, 2.71, 4),
    'KOTAKBANK': (75, -0.99, 4), 'INDUSINDBK': (67, 6.31, 3),
    'DIVISLAB': (67, 4.22, 3), 'BAJFINANCE': (67, 7.16, 3),
    'MANKIND': (67, 4.20, 3), 'LT': (67, 6.11, 3),
    'TATACOMM': (67, 3.15, 3), 'AMBUJACEM': (67, 4.47, 3),
    'WIPRO': (67, 0.97, 3), 'COALINDIA': (67, 0.45, 3),
    'VBL': (60, 4.41, 5), 'TRENT': (60, 2.79, 5),
    'GAIL': (60, 2.12, 5), 'DLF': (60, 0.29, 5),
    'HDFCBANK': (60, -1.00, 5), 'ADANIGREEN': (50, 10.63, 4),
    'COLPAL': (50, 2.32, 6), 'SHRIRAMFIN': (50, 5.50, 2),
    'TATACONSUM': (50, 3.80, 2), 'ITC': (50, 1.19, 4),
    'ADANIENT': (40, 3.32, 5), 'CHOLAFIN': (40, -0.39, 5),
}

# Overall strategy stats
STRATEGY_WIN_RATE_20D = 64.6
STRATEGY_AVG_RETURN_20D = 3.21
STRATEGY_WIN_RATE_10D = 53.4
STRATEGY_AVG_RETURN_10D = 0.95
STRATEGY_CROSSOVER_PROB = 95


def scan_strategy(ticker: str, df: pd.DataFrame) -> Optional[StrategySignal]:
    """Scan a single stock for Vinoth's Strategy entry conditions."""
    if df is None or len(df) < 50:
        return None

    df = df.copy()
    df['RSI'] = _compute_rsi(df)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = _compute_macd(df)

    last = df.iloc[-1]
    date_str = str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1])
    clean_ticker = ticker.replace('.NS', '')
    sector = get_sector(clean_ticker)
    industry = get_industry(clean_ticker)

    sig = StrategySignal(
        ticker=clean_ticker,
        sector=sector,
        industry=industry,
        date=date_str,
        close=_safe(last['Close']),
    )

    if len(df) >= 2:
        sig.change_1d = _safe((last['Close'] / df['Close'].iloc[-2] - 1) * 100)

    # RSI
    sig.rsi = _safe(last.get('RSI'))

    # RSI low in last 10 days
    lookback = min(10, len(df))
    rsi_window = df['RSI'].iloc[-lookback:]
    rsi_min_idx = rsi_window.idxmin()
    sig.rsi_low = _safe(rsi_window.min())
    sig.rsi_low_date = str(rsi_min_idx.date()) if hasattr(rsi_min_idx, 'date') else str(rsi_min_idx)
    sig.days_since_rsi_low = (df.index[-1] - rsi_min_idx).days

    # MACD histogram
    sig.macd_histogram = _safe(last.get('MACD_Hist'))
    if len(df) >= 2:
        sig.macd_hist_prev = _safe(df['MACD_Hist'].iloc[-2])

    # Histogram direction and convergence days
    hist = df['MACD_Hist'].values
    if sig.macd_histogram is not None and sig.macd_hist_prev is not None:
        if sig.macd_histogram > sig.macd_hist_prev:
            sig.macd_hist_direction = "rising"
        elif sig.macd_histogram < sig.macd_hist_prev:
            sig.macd_hist_direction = "falling"
        else:
            sig.macd_hist_direction = "flat"

    # Count consecutive days histogram has been rising while negative
    conv_days = 0
    for k in range(len(hist) - 1, 0, -1):
        if hist[k] < 0 and hist[k] > hist[k - 1]:
            conv_days += 1
        else:
            break
    sig.macd_converging_days = conv_days

    # Check if MACD just crossed (histogram turned positive in last 3 days)
    sig.macd_crossed = False
    sig.days_since_cross = 0
    for k in range(1, min(4, len(hist))):
        idx = len(hist) - k
        if idx >= 1 and hist[idx] >= 0 and hist[idx - 1] < 0:
            sig.macd_crossed = True
            sig.days_since_cross = k - 1
            break

    # ── Zone Classification ──────────────────────────────────────
    rsi_val = sig.rsi or 100
    hist_val = sig.macd_histogram or 0
    hist_rising = sig.macd_hist_direction == "rising"

    # Check if RSI was <= 35 in last 10 days
    rsi_was_low = sig.rsi_low is not None and sig.rsi_low <= 35

    if rsi_val <= 35 and hist_val < 0 and hist_rising:
        sig.zone = "entry"
        sig.zone_label = "ENTRY ZONE - RSI oversold + MACD converging"
    elif rsi_val <= 35 and hist_val < 0:
        sig.zone = "entry"
        sig.zone_label = "ENTRY ZONE - RSI oversold, MACD negative (watch for convergence)"
    elif rsi_was_low and sig.macd_crossed and sig.days_since_rsi_low <= 15:
        sig.zone = "crossed"
        sig.zone_label = f"CROSSED - MACD crossover {sig.days_since_cross}d ago (already running)"
    elif rsi_val <= 42 and rsi_val > 35 and hist_val < 0 and hist_rising:
        sig.zone = "near"
        sig.zone_label = "NEAR ZONE - RSI approaching 35, MACD converging"
    elif rsi_was_low and hist_val < 0 and hist_rising and sig.days_since_rsi_low <= 10:
        sig.zone = "crossed"  # recovering from RSI low, converging
        sig.zone_label = f"RECOVERING - RSI was {sig.rsi_low:.0f} on {sig.rsi_low_date}, MACD converging"
    else:
        sig.zone = "none"

    if sig.zone == "none":
        return None

    # ── Historical Stats ─────────────────────────────────────────
    stats = STOCK_STATS.get(clean_ticker)
    if stats:
        sig.historical_win_rate = stats[0]
        sig.historical_avg_return = stats[1]
        sig.historical_trades = stats[2]

    # ── Trade Levels ─────────────────────────────────────────────
    atr = _compute_atr(df)
    sig.atr = _safe(atr)
    if sig.close and atr:
        sig.entry_price = sig.close
        sig.stop_loss = _safe(sig.close - 1.5 * atr)
        sig.sl_pct = _safe((sig.stop_loss / sig.close - 1) * 100)
        sig.target_10d = _safe(sig.close * 1.03)   # conservative 3% (based on avg)
        sig.target_20d = _safe(sig.close * 1.05)    # 5% (40% of trades hit this)

    # ── Risk Flags ───────────────────────────────────────────────
    flags = []
    if stats and stats[0] < 40:
        flags.append(f"Low historical win rate ({stats[0]:.0f}%) for this stock")
    if stats and stats[1] < 0:
        flags.append(f"Negative historical avg return ({stats[1]:+.1f}%)")
    if sig.rsi and sig.rsi < 25:
        flags.append("RSI extremely oversold - could be fundamental breakdown, verify news")

    # Check for downtrend (price below SMA 200)
    if len(df) >= 200:
        sma200 = df['Close'].rolling(200).mean().iloc[-1]
        if sig.close and sig.close < sma200 * 0.9:
            flags.append(f"Price >10% below 200 SMA - structural downtrend")

    # Check recent drawdown
    if len(df) >= 20:
        high_20d = df['High'].iloc[-20:].max()
        if sig.close and (sig.close / high_20d - 1) * 100 < -15:
            dd = (sig.close / high_20d - 1) * 100
            flags.append(f"Down {dd:.0f}% from 20D high - heavy selling pressure")

    sig.risk_flags = flags
    return sig


def signal_to_dict(sig: StrategySignal) -> dict:
    d = asdict(sig)
    for k, v in d.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            d[k] = None
    return d
