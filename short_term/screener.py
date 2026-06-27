"""Short-term convergence screener — technicals + fundamental triggers.

The core idea: a stock becomes a short-term opportunity when BOTH
technical momentum and fundamental triggers align. Neither alone is
sufficient; convergence reduces false signals.

Scoring matrix:
    Technical score (-5 to +5) from RSI, MACD, CPR, Volume
    Fundamental triggers (0-3) from bulk deals, delivery %, insider buying
    Convergence = both positive => opportunity flagged

Timeframe: weeks to months (swing trades, not day trading)
"""

import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

import pandas as pd

from technicals.data_fetcher import fetch_daily_ohlcv
from technicals.signals import analyze_from_dataframe, TechnicalSignal
from short_term.nse_events import (
    fetch_bulk_deals, fetch_block_deals,
    get_fundamental_triggers, FundamentalTriggers,
)
from shared.utils import logger


@dataclass
class ConvergenceResult:
    ticker: str
    date: str

    # Technical
    technical: Optional[TechnicalSignal] = None
    tech_score: int = 0
    tech_action: str = "HOLD"

    # Fundamental triggers
    fundamentals: Optional[FundamentalTriggers] = None
    trigger_count: int = 0
    triggers: List[str] = field(default_factory=list)

    # Convergence
    converged: bool = False
    convergence_type: str = ""       # "STRONG", "MODERATE", "NONE"
    signal: str = "NO SIGNAL"        # "STRONG BUY", "BUY", "WATCH", "NO SIGNAL"
    reasons: List[str] = field(default_factory=list)

    # Context from thematic screening (if available)
    theme: str = ""
    segment: str = ""
    exposure: str = ""
    thematic_grade: str = ""


def screen_tickers(tickers: List[str],
                    theme_context: Optional[Dict] = None) -> List[ConvergenceResult]:
    """Screen multiple tickers for short-term convergence signals.

    Args:
        tickers: list of NSE ticker symbols
        theme_context: optional dict of {ticker: {theme, segment, exposure, grade}}
                       from thematic screening

    Returns list of ConvergenceResult, sorted by signal strength.
    """
    logger.info(f"Short-term convergence screening: {len(tickers)} tickers")

    # Pre-fetch bulk/block deals once (saves API calls)
    logger.info("  Fetching bulk/block deals...")
    bulk_deals = fetch_bulk_deals()
    block_deals = fetch_block_deals()

    results = []

    for i, ticker in enumerate(tickers):
        logger.info(f"  [{i+1}/{len(tickers)}] Screening {ticker}...")

        try:
            result = _screen_single(
                ticker, bulk_deals, block_deals,
                theme_context.get(ticker) if theme_context else None,
            )
            results.append(result)
        except Exception as e:
            logger.error(f"  Error screening {ticker}: {e}")
            results.append(ConvergenceResult(
                ticker=ticker,
                date=datetime.now().strftime("%Y-%m-%d"),
            ))

        # Rate limit between tickers
        if i < len(tickers) - 1:
            time.sleep(0.5 + random.uniform(0, 0.3))

    # Sort: converged first, then by tech_score descending
    results.sort(key=lambda r: (
        -int(r.converged),
        -_signal_rank(r.signal),
        -r.tech_score,
    ))

    # Summary
    converged_count = sum(1 for r in results if r.converged)
    logger.info(f"Convergence screening complete: {converged_count}/{len(results)} signals found")

    return results


def screen_theme_short_term(theme_slug: str) -> List[ConvergenceResult]:
    """Run short-term convergence screen on all tickers in a theme.

    Combines thematic context with technical + fundamental triggers.
    """
    from themes.registry import get_theme

    theme = get_theme(theme_slug)
    if not theme:
        logger.error(f"Theme '{theme_slug}' not found")
        return []

    # Build theme context
    theme_context = {}
    for seg in theme.segments:
        for co in seg.companies:
            theme_context[co.ticker] = {
                "theme": theme.name,
                "segment": seg.name,
                "exposure": co.exposure,
            }

    return screen_tickers(theme.all_tickers, theme_context=theme_context)


def _screen_single(ticker: str,
                     bulk_deals, block_deals,
                     theme_info: Optional[Dict] = None) -> ConvergenceResult:
    """Screen a single ticker for convergence."""
    result = ConvergenceResult(
        ticker=ticker,
        date=datetime.now().strftime("%Y-%m-%d"),
    )

    # Add theme context if available
    if theme_info:
        result.theme = theme_info.get("theme", "")
        result.segment = theme_info.get("segment", "")
        result.exposure = theme_info.get("exposure", "")
        result.thematic_grade = theme_info.get("grade", "")

    # ── Technical analysis ───────────────────────────────────────────────
    df = fetch_daily_ohlcv(ticker, days=365)
    if df is not None:
        tech = analyze_from_dataframe(ticker, df)
        if tech:
            result.technical = tech
            result.tech_score = tech.score
            result.tech_action = tech.action

    # ── Fundamental triggers ─────────────────────────────────────────────
    fund = get_fundamental_triggers(ticker, bulk_deals, block_deals)
    result.fundamentals = fund
    result.trigger_count = fund.trigger_count
    result.triggers = fund.triggers

    # ── Convergence logic ────────────────────────────────────────────────
    tech_positive = result.tech_score >= 2
    tech_strong = result.tech_score >= 4
    fund_positive = result.trigger_count >= 1
    fund_strong = result.trigger_count >= 2

    reasons = []

    if tech_strong and fund_strong:
        result.converged = True
        result.convergence_type = "STRONG"
        result.signal = "STRONG BUY"
        reasons.append("Strong technical + multiple fundamental triggers")
    elif tech_strong and fund_positive:
        result.converged = True
        result.convergence_type = "STRONG"
        result.signal = "STRONG BUY"
        reasons.append("Strong technical momentum + fundamental trigger")
    elif tech_positive and fund_strong:
        result.converged = True
        result.convergence_type = "MODERATE"
        result.signal = "BUY"
        reasons.append("Positive technicals + strong fundamental triggers")
    elif tech_positive and fund_positive:
        result.converged = True
        result.convergence_type = "MODERATE"
        result.signal = "BUY"
        reasons.append("Technical + fundamental alignment")
    elif tech_positive:
        result.convergence_type = "NONE"
        result.signal = "WATCH"
        reasons.append("Positive technicals, awaiting fundamental confirmation")
    elif fund_positive:
        result.convergence_type = "NONE"
        result.signal = "WATCH"
        reasons.append("Fundamental triggers present, technicals not ready")
    else:
        result.convergence_type = "NONE"
        result.signal = "NO SIGNAL"

    # Add technical reasons
    if result.technical:
        reasons.extend(result.technical.reasons)

    # Add fundamental triggers
    reasons.extend(result.triggers)

    # Add theme context if relevant
    if result.exposure == "high" and result.converged:
        reasons.append(f"High exposure to {result.theme}")

    result.reasons = reasons
    return result


def _signal_rank(signal: str) -> int:
    return {
        "STRONG BUY": 4,
        "BUY": 3,
        "WATCH": 2,
        "NO SIGNAL": 1,
    }.get(signal, 0)


# ═══════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════

def format_convergence_report(results: List[ConvergenceResult],
                               title: str = "Short-Term Convergence Screen") -> str:
    """Format convergence results as a markdown report."""
    lines = [
        f"# {title}",
        f"*Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        f"*Screened: {len(results)} stocks*",
        "",
    ]

    # Summary
    strong_buys = [r for r in results if r.signal == "STRONG BUY"]
    buys = [r for r in results if r.signal == "BUY"]
    watches = [r for r in results if r.signal == "WATCH"]

    lines.append(f"## Summary")
    lines.append(f"- **STRONG BUY:** {len(strong_buys)}")
    lines.append(f"- **BUY:** {len(buys)}")
    lines.append(f"- **WATCH:** {len(watches)}")
    lines.append("")

    # Detailed results for converged signals
    if strong_buys or buys:
        lines.append("## Opportunities")
        lines.append("")
        lines.append("| Ticker | Signal | Tech Score | Triggers | RSI | MACD | CPR | Volume | Reasons |")
        lines.append("|--------|--------|-----------|----------|-----|------|-----|--------|---------|")

        for r in strong_buys + buys:
            tech = r.technical
            rsi = f"{tech.rsi:.0f}" if tech and tech.rsi else "N/A"
            macd_s = tech.macd_signal if tech else "N/A"
            cpr_s = tech.cpr_signal if tech else "N/A"
            vol_s = tech.volume_signal if tech else "N/A"
            reasons = "; ".join(r.reasons[:3])

            theme_tag = f" [{r.exposure}]" if r.exposure else ""
            lines.append(
                f"| {r.ticker}{theme_tag} | **{r.signal}** | {r.tech_score} | "
                f"{r.trigger_count} | {rsi} | {macd_s} | {cpr_s} | {vol_s} | {reasons} |"
            )

        lines.append("")

    # Watchlist
    if watches:
        lines.append("## Watchlist")
        lines.append("")
        for r in watches:
            reason_str = "; ".join(r.reasons[:2])
            lines.append(f"- **{r.ticker}** — {reason_str}")
        lines.append("")

    return "\n".join(lines)
