"""Opportunity Tab — the focused shortlist.

Shows only the top conviction BUY and SELL opportunities with:
- Clear WHY (reasons visible in the table, not hidden)
- Risk flags (what could go wrong)
- Tech + Flow scores shown independently
- SL/Target with source labels
- Position sizing

This is the "open this tab, make decisions" view.
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
from dashboard.sectors import get_sector, get_industry, get_sector_industry
from dashboard.generator import analyze_for_dashboard
from dashboard.money_flow import analyze_money_flow
from dashboard.trade_planner import (
    compute_market_regime, compute_atr,
    find_support_resistance, _safe, TradePlan,
)
from shared.utils import logger

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY50_SYMBOL = "^NSEI"

MAX_BUY_OPPORTUNITIES = 15
MAX_SELL_OPPORTUNITIES = 10


@dataclass
class Opportunity:
    ticker: str
    sector: str = ""
    industry: str = ""
    close: Optional[float] = None
    date: str = ""

    # Scores — shown independently, not combined
    tech_score: int = 0
    tech_max: int = 16
    tech_action: str = "HOLD"
    flow_score: int = 0
    flow_max: int = 10
    flow_action: str = "HOLD"

    # Alignment: do tech and flow agree?
    alignment: str = "neutral"  # strong, partial, conflict
    alignment_label: str = ""

    # Signal category: money flow + technical phase
    signal_category: str = "neutral"  # confirmed, early, unconfirmed, trap
    category_label: str = ""

    # The WHY — visible in the table
    primary_reason: str = ""    # single strongest signal
    secondary_reasons: List[str] = field(default_factory=list)

    # Risk flags — what could go wrong
    risk_flags: List[str] = field(default_factory=list)

    # Trade levels
    stop_loss: Optional[float] = None
    sl_pct: Optional[float] = None
    sl_source: str = ""
    target: Optional[float] = None
    target_pct: Optional[float] = None
    target_source: str = ""
    risk_reward: Optional[float] = None

    # Context
    change_1d: Optional[float] = None
    change_5d: Optional[float] = None
    change_20d: Optional[float] = None
    dist_from_52w_high: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    support: Optional[float] = None
    resistance: Optional[float] = None
    atr: Optional[float] = None

    # Position sizing
    risk_per_share: Optional[float] = None

    # Side
    side: str = "BUY"  # BUY or SELL


def _detect_risk_flags(ticker: str, df: pd.DataFrame, tech_sig, mf_sig,
                        sr: Dict, sector_buy_counts: Dict) -> List[str]:
    """Detect what could go wrong with this trade."""
    flags = []
    close = df["Close"].iloc[-1]

    # 1. Near 52-week high (extended, limited upside)
    high_52w = df["High"].max()
    if high_52w > 0:
        dist = (close / high_52w - 1) * 100
        if dist > -3:
            flags.append("Near 52W high — limited upside, potential reversal")

    # 2. RSI overbought (for buy) or oversold (for sell)
    if tech_sig.rsi and tech_sig.rsi > 65:
        flags.append(f"RSI elevated ({tech_sig.rsi:.0f}) — momentum may be stretched")
    if tech_sig.rsi and tech_sig.rsi > 75:
        flags.append(f"RSI overbought ({tech_sig.rsi:.0f}) — high risk of mean reversion")

    # 3. Target is very close (less than 2% upside)
    if sr["resistance"]:
        upside = (sr["resistance"] / close - 1) * 100
        if upside < 2:
            flags.append(f"Resistance only +{upside:.1f}% away — thin margin")

    # 4. Tech and flow disagree
    if tech_sig.score > 2 and mf_sig.money_flow_score < -1:
        flags.append("Money flow negative despite bullish technicals — smart money may be exiting")
    if tech_sig.score < -2 and mf_sig.money_flow_score > 1:
        flags.append("Technicals bearish but money flowing in — could be early accumulation")

    # 5. Volume drying up
    if tech_sig.volume_ratio and tech_sig.volume_ratio < 0.6:
        flags.append(f"Low volume ({tech_sig.volume_ratio:.1f}x avg) — move lacks conviction")

    # 6. Sector concentration
    sector = get_sector(ticker)
    if sector_buy_counts.get(sector, 0) >= 3:
        flags.append(f"{sector} sector already has {sector_buy_counts[sector]} opportunities — concentration risk")

    # 7. Wide stop loss
    if sr["support"]:
        sl_dist = (sr["support"] / close - 1) * 100
        if sl_dist < -8:
            flags.append(f"Support is {sl_dist:.0f}% away — wide stop loss, large risk per share")

    return flags


def _determine_alignment(tech_score: int, flow_score: int) -> tuple:
    """Determine if technical and money flow signals agree."""
    tech_bullish = tech_score >= 3
    tech_bearish = tech_score <= -2
    flow_bullish = flow_score >= 2
    flow_bearish = flow_score <= -2

    if tech_bullish and flow_bullish:
        return "strong", "Tech + Flow ALIGNED bullish"
    if tech_bearish and flow_bearish:
        return "strong", "Tech + Flow ALIGNED bearish"
    if tech_bullish and flow_bearish:
        return "conflict", "CONFLICT: Tech bullish, Flow bearish"
    if tech_bearish and flow_bullish:
        return "conflict", "CONFLICT: Tech bearish, Flow bullish"
    if tech_bullish or flow_bullish:
        return "partial", "Partial: one side bullish, other neutral"
    if tech_bearish or flow_bearish:
        return "partial", "Partial: one side bearish, other neutral"
    return "neutral", "Both neutral — no clear signal"


def _determine_category(tech_score: int, flow_score: int) -> tuple:
    """Classify the stock into a signal category based on money-flow-leads-technicals framework.

    Category 1 — CONFIRMED:    Money flow positive AND technicals triggered (highest conviction)
    Category 2 — EARLY:        Money flow positive but technicals haven't triggered yet (watch for entry)
    Category 3 — UNCONFIRMED:  Technicals triggered but money flow is weak (move lacks fuel)
    Category 4 — TRAP:         Technicals triggered but money flow is negative (smart money exiting)
    """
    mf_positive = flow_score >= 3
    tech_triggered = tech_score >= 4
    tech_moderate = tech_score >= 1
    mf_negative = flow_score <= -1

    if mf_positive and tech_triggered:
        return "confirmed", "CONFIRMED — Money flow + technicals aligned"
    if mf_positive and not tech_triggered:
        return "early", "EARLY — Money leading, technicals pending"
    if tech_moderate and mf_negative:
        return "trap", "TRAP — Technicals up, money flowing out"
    if tech_triggered and not mf_positive:
        return "unconfirmed", "UNCONFIRMED — Technicals up, no flow backing"
    return "neutral", ""


def _pick_primary_reason(tech_reasons: List[str], mf_reasons: List[str],
                          alignment: str) -> str:
    """Pick the single most important reason for this opportunity."""
    # Prioritize alignment-based summary
    if alignment == "strong":
        return "Both technicals and money flow confirm the move"
    if alignment == "conflict":
        return "Technicals and money flow disagree — proceed with caution"

    # Otherwise pick the strongest individual signal
    # Technical reasons with backtest evidence go first
    for r in tech_reasons:
        if "WR" in r or "PF" in r:
            return r.replace("[T] ", "")
    if tech_reasons:
        return tech_reasons[0].replace("[T] ", "")
    if mf_reasons:
        return mf_reasons[0].replace("[M] ", "")
    return "Marginal signals"


def build_opportunity(ticker: str, df: pd.DataFrame,
                       benchmark_df: pd.DataFrame,
                       sector_buy_counts: Dict) -> Optional[Opportunity]:
    """Build an opportunity assessment for a single stock."""
    if df is None or len(df) < 50:
        return None

    tech_sig = analyze_for_dashboard(ticker, df.copy(), benchmark_df=benchmark_df)
    mf_sig = analyze_money_flow(ticker, df.copy())

    if tech_sig is None or mf_sig is None:
        return None

    close = df["Close"].iloc[-1]
    sector, industry = get_sector_industry(ticker)
    sr = find_support_resistance(df)
    atr = compute_atr(df)

    opp = Opportunity(
        ticker=ticker,
        sector=sector,
        industry=industry,
        close=_safe(close),
        date=tech_sig.date,
        tech_score=tech_sig.score,
        tech_action=tech_sig.action,
        flow_score=mf_sig.money_flow_score,
        flow_action=mf_sig.action,
        change_1d=tech_sig.change_1d,
        change_5d=tech_sig.change_5d,
        change_20d=tech_sig.change_20d,
        high_52w=sr["high_52w"],
        low_52w=sr["low_52w"],
        support=sr["support"],
        resistance=sr["resistance"],
        atr=atr,
    )

    if opp.high_52w and close:
        opp.dist_from_52w_high = _safe((close / opp.high_52w - 1) * 100)

    # ── Alignment ────────────────────────────────────────────────
    opp.alignment, opp.alignment_label = _determine_alignment(
        tech_sig.score, mf_sig.money_flow_score)

    # ── Signal Category (money-leads-technicals framework) ──────
    opp.signal_category, opp.category_label = _determine_category(
        tech_sig.score, mf_sig.money_flow_score)

    # ── Reasons (WHY) ────────────────────────────────────────────
    tech_reasons = [f"[T] {r}" for r in tech_sig.reasons[:4]]
    mf_reasons = [f"[M] {r}" for r in mf_sig.reasons[:3]]
    opp.primary_reason = _pick_primary_reason(tech_reasons, mf_reasons, opp.alignment)
    opp.secondary_reasons = tech_reasons + mf_reasons

    # ── SL / Target from chart structure ─────────────────────────
    if close and atr:
        noise_floor = close - 1.0 * atr
        atr_sl = close - 1.5 * atr
        max_distance = 2.0 * atr

        if sr["support"]:
            support_dist = close - sr["support"]
            sl_from_support = sr["support"] * 0.995

            if support_dist <= max_distance:
                # Support is nearby — use it, respect noise floor
                opp.stop_loss = _safe(max(sl_from_support, noise_floor))
                opp.sl_source = sr.get("support_type", "swing_low")
            else:
                # Support too far for short-term — use ATR
                opp.stop_loss = _safe(atr_sl)
                opp.sl_source = "1.5x_atr"
        else:
            opp.stop_loss = _safe(atr_sl)
            opp.sl_source = "1.5x_atr"

        if opp.stop_loss:
            opp.sl_pct = _safe((opp.stop_loss / close - 1) * 100)
            opp.risk_per_share = _safe(close - opp.stop_loss)

    if close and atr:
        # Use swing resistance if it gives >= 2% upside, else fall back to ATR
        if sr["resistance"]:
            swing_pct = (sr["resistance"] / close - 1) * 100
            if swing_pct >= 2.0:
                opp.target = sr["resistance"]
                opp.target_source = sr["resistance_type"]
            else:
                # Swing resistance too close — use 2x ATR target
                opp.target = _safe(close + 2.0 * atr)
                opp.target_source = "2x_atr"
        else:
            opp.target = _safe(close + 2.0 * atr)
            opp.target_source = "2x_atr"

        if opp.target:
            opp.target_pct = _safe((opp.target / close - 1) * 100)

    if opp.risk_per_share and opp.target and close and opp.risk_per_share > 0:
        reward = opp.target - close
        if reward > 0:
            opp.risk_reward = _safe(reward / opp.risk_per_share)

    # ── Risk Flags ───────────────────────────────────────────────
    opp.risk_flags = _detect_risk_flags(ticker, df, tech_sig, mf_sig,
                                         sr, sector_buy_counts)

    # ── Side ─────────────────────────────────────────────────────
    if tech_sig.score <= -3 or mf_sig.money_flow_score <= -3:
        opp.side = "SELL"
    else:
        opp.side = "BUY"

    return opp


def _conviction_score(opp: Opportunity) -> float:
    """Score for ranking opportunities by conviction.

    Higher = more conviction. Considers:
    - Signal strength (tech + flow scores)
    - Alignment (agreement between tech and flow)
    - Risk/reward quality (hard gate: R:R < 1.0 = near-zero conviction)
    - Volume confirmation
    - Extended move penalty
    - 52W high proximity penalty
    """
    base = abs(opp.tech_score) * 3 + abs(opp.flow_score) * 2

    # Alignment bonus
    if opp.alignment == "strong":
        base *= 1.5
    elif opp.alignment == "conflict":
        base *= 0.5

    # Signal category adjustment (money-leads-technicals)
    if opp.signal_category == "confirmed":
        base *= 1.4  # highest conviction: both dimensions agree
    elif opp.signal_category == "trap":
        base *= 0.3  # smart money exiting despite bullish chart

    # R:R — hard gate and scaling
    if opp.risk_reward is None or opp.risk_reward < 1.0:
        base *= 0.1  # near-zero: negative expected value
    elif opp.risk_reward < 1.5:
        base *= 0.6  # marginal
    elif opp.risk_reward >= 2.5:
        base *= 1.4  # excellent
    elif opp.risk_reward >= 2.0:
        base *= 1.3
    elif opp.risk_reward >= 1.5:
        base *= 1.1

    # Penalty for too many risk flags
    if len(opp.risk_flags) >= 3:
        base *= 0.7

    # Extended move penalty — chasing a stock that already ran
    if opp.change_20d and opp.change_20d > 15:
        base *= 0.5  # already rallied >15% in 20 days

    # 52W high proximity penalty — unless volume confirms breakout
    if opp.dist_from_52w_high is not None and opp.dist_from_52w_high > -2:
        # Within 2% of 52W high — risky unless volume is high
        has_volume_flag = any("Low volume" in f for f in opp.risk_flags)
        if has_volume_flag:
            base *= 0.3  # approaching ceiling on low volume
        else:
            base *= 0.7  # approaching ceiling, but at least volume is there

    # Low volume penalty — move lacks institutional backing
    has_low_vol = any("Low volume" in f or "volume" in f.lower() and "low" in f.lower()
                      for f in opp.risk_flags)
    if has_low_vol:
        base *= 0.5

    return round(base, 1)


def _opp_to_dict(o: Opportunity) -> dict:
    d = asdict(o)
    for k, v in d.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            d[k] = None
    d["conviction"] = _conviction_score(o)
    return d

