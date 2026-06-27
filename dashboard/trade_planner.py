"""Trade Planner — the decision-making dashboard.

Combines Technical Signals (Tab 1) + Money Flow (Tab 2) into actionable
trade plans with stop loss, target, R:R ratio, position sizing, market
regime filter, and sector concentration checks.

This is Tab 3: the "what do I actually do?" tab.
"""

import os
import json
import time
import random
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Tuple

import pandas as pd
import numpy as np

from technicals.indicators import compute_all_indicators
from technicals.data_fetcher import fetch_daily_ohlcv
from dashboard.nifty100 import NIFTY_100
from dashboard.sectors import get_sector, get_industry, get_sector_industry
from dashboard.generator import analyze_for_dashboard
from dashboard.money_flow import analyze_money_flow
from shared.utils import logger

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY50_SYMBOL = "^NSEI"


@dataclass
class TradePlan:
    ticker: str
    sector: str = ""
    industry: str = ""
    date: str = ""
    close: Optional[float] = None
    change_1d: Optional[float] = None

    # Scores from both dashboards
    technical_score: int = 0
    money_flow_score: int = 0
    combined_score: float = 0.0

    # Market regime
    market_regime: str = "unknown"  # bull, bear, sideways
    nifty_trend: str = ""

    # Stop Loss (ATR-based)
    atr_14: Optional[float] = None
    stop_loss: Optional[float] = None
    sl_pct: Optional[float] = None  # stop loss as % from close

    # Target (nearest resistance)
    target: Optional[float] = None
    target_pct: Optional[float] = None  # target as % from close
    resistance_type: str = ""  # "52w_high", "20d_high", "pivot_r1"

    # Risk:Reward
    risk_reward: Optional[float] = None

    # Position sizing
    risk_per_share: Optional[float] = None  # close - stop_loss

    # Support/Resistance context
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    dist_from_52w_high: Optional[float] = None  # % below 52-week high
    support_level: Optional[float] = None
    support_type: str = ""
    resistance_level: Optional[float] = None

    # Key signals summary
    technical_action: str = "HOLD"
    money_flow_action: str = "HOLD"
    top_reasons: List[str] = field(default_factory=list)

    # Final action
    action: str = "WAIT"  # ENTER, WAIT, AVOID, EXIT
    action_reason: str = ""


def _safe(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) or np.isinf(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


def compute_market_regime(benchmark_df: pd.DataFrame) -> Tuple[str, str]:
    """Determine market regime from Nifty 50 trend.

    Returns: (regime, description)
        regime: 'bull', 'bear', 'sideways'
        description: human-readable market context
    """
    if benchmark_df is None or len(benchmark_df) < 50:
        return "unknown", "Insufficient benchmark data"

    close = benchmark_df["Close"].iloc[-1]
    ema_20 = benchmark_df["Close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema_50 = benchmark_df["Close"].ewm(span=50, adjust=False).mean().iloc[-1]

    if pd.isna(close) or pd.isna(ema_20) or pd.isna(ema_50):
        return "unknown", "Insufficient data"

    # 20-day change for context
    if len(benchmark_df) >= 20:
        chg_20d = (close / benchmark_df["Close"].iloc[-20] - 1) * 100
    else:
        chg_20d = 0

    if close > ema_20 > ema_50:
        if chg_20d > 3:
            return "bull", f"Nifty BULLISH — price above EMA 20 > 50, +{chg_20d:.1f}% in 20D"
        return "bull", f"Nifty BULLISH — price above EMA 20 > 50"
    elif close < ema_20 < ema_50:
        return "bear", f"Nifty BEARISH — price below EMA 20 < 50, {chg_20d:+.1f}% in 20D"
    else:
        return "sideways", f"Nifty SIDEWAYS — mixed signals, {chg_20d:+.1f}% in 20D"


def compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Compute current ATR (Average True Range)."""
    if len(df) < period + 1:
        return None
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift(1)).abs()
    tr3 = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    val = atr.iloc[-1]
    return _safe(val) if pd.notna(val) else None


def _find_swing_points(df: pd.DataFrame, lookback: int = 5) -> Dict:
    """Detect swing highs and swing lows from price action.

    A swing low: bar whose Low is lower than the Low of `lookback` bars
    on either side. These are levels where buyers actually stepped in.

    A swing high: bar whose High is higher than the High of `lookback` bars
    on either side. These are levels where sellers appeared.

    This is how a real trader reads a chart.
    """
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    swing_highs = []  # (index, price)
    swing_lows = []   # (index, price)

    for i in range(lookback, n - lookback):
        # Swing high: higher than all neighbors
        is_swing_high = True
        for j in range(1, lookback + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing_high = False
                break
        if is_swing_high:
            swing_highs.append((i, float(highs[i])))

        # Swing low: lower than all neighbors
        is_swing_low = True
        for j in range(1, lookback + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_swing_low = False
                break
        if is_swing_low:
            swing_lows.append((i, float(lows[i])))

    return {"swing_highs": swing_highs, "swing_lows": swing_lows}


def find_support_resistance(df: pd.DataFrame) -> Dict:
    """Find support and resistance from actual chart structure.

    How a successful trader does it:
    1. Find swing lows (where buyers stepped in) → these are support
    2. Find swing highs (where sellers appeared) → these are resistance
    3. SL goes just below nearest support
    4. Target goes at nearest resistance above price
    5. R:R is a consequence of these real levels

    Fallbacks when structure is unclear:
    - SMA 50 as dynamic support
    - ATR-based if no clear swing points exist
    """
    result = {
        "high_52w": None, "low_52w": None,
        "support": None, "support_type": "",
        "resistance": None, "resistance_type": "",
    }

    if len(df) < 30:
        return result

    close = df["Close"].iloc[-1]
    result["high_52w"] = _safe(df["High"].max())
    result["low_52w"] = _safe(df["Low"].min())

    # ── Detect swing points from chart ───────────────────────────
    # Only use recent 100 bars for swing detection — old levels are stale
    recent_df = df.iloc[-100:] if len(df) > 100 else df
    recent_offset = len(df) - len(recent_df)
    swings = _find_swing_points(recent_df, lookback=5)
    # Adjust indices back to full df
    swing_lows = [(idx + recent_offset, price) for idx, price in swings["swing_lows"]]
    swing_highs = [(idx + recent_offset, price) for idx, price in swings["swing_highs"]]

    # ── SUPPORT: nearest swing low below current price ───────────
    # A real support level is where price previously bounced.
    # We want the NEAREST one below price (most relevant).
    supports_below = [(idx, price) for idx, price in swing_lows
                       if price < close * 0.995]  # at least 0.5% below

    if supports_below:
        # Pick the highest swing low below price (nearest support)
        supports_below.sort(key=lambda x: x[1], reverse=True)
        result["support"] = _safe(supports_below[0][1])
        result["support_type"] = "swing_low"
    else:
        # Fallback: SMA 50 as dynamic support
        if len(df) >= 50:
            sma50 = df["Close"].rolling(50).mean().iloc[-1]
            if pd.notna(sma50) and sma50 < close * 0.995:
                result["support"] = _safe(sma50)
                result["support_type"] = "sma_50"

    # ── RESISTANCE: nearest swing high above current price ───────
    # A real resistance is where price previously failed to break.
    resistances_above = [(idx, price) for idx, price in swing_highs
                          if price > close * 1.005]  # at least 0.5% above

    if resistances_above:
        # Pick the lowest swing high above price (nearest resistance)
        resistances_above.sort(key=lambda x: x[1])
        nearest = resistances_above[0][1]
        # Cap at 15% for short-term trades
        if nearest <= close * 1.15:
            result["resistance"] = _safe(nearest)
            result["resistance_type"] = "swing_high"
        elif len(resistances_above) > 1:
            # Try next resistance if first is too far
            for _, price in resistances_above:
                if price <= close * 1.15:
                    result["resistance"] = _safe(price)
                    result["resistance_type"] = "swing_high"
                    break

    # Fallback: ATR-based target if no clear swing high
    if result["resistance"] is None:
        atr = compute_atr(df)
        if atr and atr > 0:
            result["resistance"] = _safe(close + 2 * atr)
            result["resistance_type"] = "2x_atr"

    return result


def build_trade_plan(ticker: str, df: pd.DataFrame,
                      benchmark_df: pd.DataFrame,
                      market_regime: str,
                      market_desc: str) -> Optional[TradePlan]:
    """Build a complete trade plan for a single stock."""
    if df is None or len(df) < 50:
        return None

    # Get technical and money flow signals
    tech_sig = analyze_for_dashboard(ticker, df.copy(), benchmark_df=benchmark_df)
    mf_sig = analyze_money_flow(ticker, df.copy())

    if tech_sig is None or mf_sig is None:
        return None

    close = df["Close"].iloc[-1]
    sector, industry = get_sector_industry(ticker)

    plan = TradePlan(
        ticker=ticker,
        sector=sector,
        industry=industry,
        date=tech_sig.date,
        close=_safe(close),
        change_1d=tech_sig.change_1d,
        technical_score=tech_sig.score,
        money_flow_score=mf_sig.money_flow_score,
        market_regime=market_regime,
        nifty_trend=market_desc,
        technical_action=tech_sig.action,
        money_flow_action=mf_sig.action,
    )

    # Combined score: technical (60% weight) + money flow (40% weight)
    # Normalize to common scale first
    tech_norm = tech_sig.score / 16.0  # -1 to +1
    mf_norm = mf_sig.money_flow_score / 10.0  # -1 to +1
    plan.combined_score = round((tech_norm * 0.6 + mf_norm * 0.4) * 100, 1)

    # Top reasons (merge from both)
    reasons = []
    for r in tech_sig.reasons[:3]:
        reasons.append(f"[T] {r}")
    for r in mf_sig.reasons[:2]:
        reasons.append(f"[M] {r}")
    plan.top_reasons = reasons

    # ── Support / Resistance from chart structure ──────────────
    sr = find_support_resistance(df)
    plan.high_52w = sr["high_52w"]
    plan.low_52w = sr["low_52w"]
    plan.support_level = sr["support"]
    plan.support_type = sr.get("support_type", "")
    plan.resistance_level = sr["resistance"]
    plan.resistance_type = sr["resistance_type"]

    if plan.high_52w and close:
        plan.dist_from_52w_high = _safe((close / plan.high_52w - 1) * 100)

    # ── ATR (used as minimum buffer, not the primary SL) ─────────
    atr = compute_atr(df)
    plan.atr_14 = atr

    # ── STOP LOSS ────────────────────────────────────────────────
    # For short-term positional (2-4 week hold):
    #
    # 1. If support is nearby (within 2x ATR from close):
    #    → SL just below support (support × 0.995)
    #    → but never tighter than 1×ATR (noise protection)
    #
    # 2. If support is far (beyond 2x ATR):
    #    → support is from a different price regime, ignore it
    #    → use 1.5×ATR as SL (standard positional distance)
    #
    # 3. No support found: use 1.5×ATR
    if close and atr:
        noise_floor = close - 1.0 * atr   # never tighter than this
        atr_sl = close - 1.5 * atr        # default positional SL
        max_distance = 2.0 * atr          # support beyond this is stale

        if sr["support"]:
            support_dist = close - sr["support"]
            sl_from_support = sr["support"] * 0.995

            if support_dist <= max_distance:
                # Support is nearby — use it, but respect noise floor
                plan.stop_loss = _safe(max(sl_from_support, noise_floor))
            else:
                # Support is too far for short-term — use ATR
                plan.stop_loss = _safe(atr_sl)
        else:
            plan.stop_loss = _safe(atr_sl)

        if plan.stop_loss:
            plan.sl_pct = _safe((plan.stop_loss / close - 1) * 100)
            plan.risk_per_share = _safe(close - plan.stop_loss)

    # ── TARGET: nearest resistance ───────────────────────────────
    if sr["resistance"] and close:
        plan.target = sr["resistance"]
        plan.target_pct = _safe((plan.target / close - 1) * 100)

    # ── Risk:Reward Ratio ────────────────────────────────────────
    if plan.risk_per_share and plan.target and close and plan.risk_per_share > 0:
        reward = plan.target - close
        if reward > 0:
            plan.risk_reward = _safe(reward / plan.risk_per_share)

    # ── Final Action Decision ────────────────────────────────────
    plan.action, plan.action_reason = _decide_action(plan)

    return plan


def _decide_action(plan: TradePlan) -> Tuple[str, str]:
    """Determine final action based on all signals + regime + R:R.

    Decision hierarchy:
    1. Market regime filter (bear market → suppress buys)
    2. Combined score threshold
    3. Risk:Reward minimum (1:2)
    4. Sector/technical confluence
    """

    # Bear market override
    if plan.market_regime == "bear":
        if plan.combined_score > 30:
            return "WAIT", "Bear market — signal is strong but wait for regime shift"
        return "AVOID", "Bear market — suppress buy signals"

    # Strong combined signal (>= 35)
    if plan.combined_score >= 35:
        if plan.risk_reward and plan.risk_reward >= 1.5:
            return "ENTER", f"Strong signal ({plan.combined_score:+.0f}) + R:R {plan.risk_reward:.1f}:1"
        elif plan.risk_reward and plan.risk_reward >= 1.0:
            return "ENTER", f"Strong signal ({plan.combined_score:+.0f}) + R:R {plan.risk_reward:.1f}:1 (tight SL)"
        elif plan.risk_reward is None:
            return "ENTER", f"Strong signal ({plan.combined_score:+.0f}) — near highs, use trailing SL"
        return "WAIT", f"Strong signal but poor R:R ({plan.risk_reward:.1f}:1)"

    # Good combined signal (>= 18)
    if plan.combined_score >= 18:
        if plan.risk_reward and plan.risk_reward >= 1.5:
            return "ENTER", f"Good signal ({plan.combined_score:+.0f}) + R:R {plan.risk_reward:.1f}:1"
        elif plan.risk_reward and plan.risk_reward >= 1.0:
            return "ENTER", f"Good signal ({plan.combined_score:+.0f}) + R:R {plan.risk_reward:.1f}:1 (tight SL)"
        elif plan.risk_reward is None:
            return "ENTER", f"Good signal ({plan.combined_score:+.0f}) — near highs, use trailing SL"
        return "WAIT", f"Good signal but R:R too low ({plan.risk_reward:.1f}:1)"

    # Mild positive (>= 5)
    if plan.combined_score >= 5:
        if plan.risk_reward and plan.risk_reward >= 2.0:
            return "WAIT", f"Weak signal ({plan.combined_score:+.0f}) but decent R:R {plan.risk_reward:.1f}:1 — wait for confirmation"
        return "WAIT", f"Weak signal ({plan.combined_score:+.0f}) — no clear edge yet"

    # Negative signals
    if plan.combined_score <= -30:
        return "EXIT", f"Strong sell signal ({plan.combined_score:+.0f})"

    if plan.combined_score <= -15:
        return "AVOID", f"Bearish ({plan.combined_score:+.0f}) — stay away"

    if plan.combined_score <= -5:
        return "AVOID", f"Weak/negative ({plan.combined_score:+.0f})"

    return "WAIT", f"Neutral ({plan.combined_score:+.0f}) — no clear edge"


def _plan_to_dict(p: TradePlan) -> dict:
    d = asdict(p)
    for k, v in d.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            d[k] = None
    return d

