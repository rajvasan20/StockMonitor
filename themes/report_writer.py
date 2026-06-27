"""Report writer for thematic and technical screens.

Saves markdown reports to output/ that can be viewed anytime in Obsidian
or any markdown viewer. Also generates a consolidated dashboard.
"""

import os
from datetime import datetime
from typing import List, Dict, Optional

from config import OUTPUT_DIR
from shared.utils import logger


THEME_REPORTS_DIR = os.path.join(OUTPUT_DIR, "theme_screens")
TECH_REPORTS_DIR = os.path.join(OUTPUT_DIR, "technical_screens")
DASHBOARD_PATH = os.path.join(OUTPUT_DIR, "DASHBOARD.md")


def save_thematic_report(results, theme_name: str, theme_slug: str) -> str:
    """Save thematic screen results as markdown. Returns file path."""
    os.makedirs(THEME_REPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{theme_slug}_{ts}.md"
    filepath = os.path.join(THEME_REPORTS_DIR, filename)

    lines = [
        f"# Thematic Screen: {theme_name}",
        f"*Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        f"*Screened: {len(results)} stocks*",
        "",
    ]

    # Summary counts
    grades = {"A": [], "B": [], "C": [], "D": []}
    for r in results:
        grades[r.grade].append(r)

    lines.append("## Summary")
    lines.append(f"- **Grade A (STRONG BUY):** {len(grades['A'])}")
    lines.append(f"- **Grade B (BUY):** {len(grades['B'])}")
    lines.append(f"- **Grade C (WATCHLIST):** {len(grades['C'])}")
    lines.append(f"- **Grade D (AVOID):** {len(grades['D'])}")
    lines.append("")

    # Main table
    lines.append("## Full Results")
    lines.append("")
    lines.append("| Ticker | Company | Grade | Exposure | Checks | Verdict | Trap | Segment |")
    lines.append("|--------|---------|-------|----------|--------|---------|------|---------|")

    for r in results:
        lines.append(
            f"| {r.ticker} | {r.company_name} | **{r.grade}** ({r.grade_label}) | "
            f"{r.exposure} | {r.checks_passed}/{r.checks_total} | "
            f"{r.verdict} | {r.value_trap_label} | {r.segment} |"
        )
    lines.append("")

    # Detail for Grade A and B
    top = grades["A"] + grades["B"]
    if top:
        lines.append("## Grade A & B — Detail")
        lines.append("")
        for r in top:
            lines.append(f"### {r.ticker} — {r.company_name}")
            lines.append(f"- **Grade:** {r.grade} ({r.grade_label})")
            lines.append(f"- **Segment:** {r.segment} | Exposure: {r.exposure}")
            lines.append(f"- **CMP:** {r.cmp:,.2f}" if r.cmp else "- **CMP:** N/A")
            if r.composite_iv:
                lines.append(f"- **Intrinsic Value:** {r.composite_iv:,.2f}")
            if r.upside_pct is not None:
                lines.append(f"- **Upside:** {r.upside_pct*100:+.1f}%")
            lines.append(f"- **Verdict:** {r.verdict} | Trap: {r.value_trap_label}")

            lines.append(f"- **Checks ({r.checks_passed}/{r.checks_total}):**")
            for c in r.checks:
                icon = "PASS" if c.passed else "FAIL"
                val = f" = {c.value}" if c.value else ""
                lines.append(f"  - [{icon}] {c.name}{val} (threshold: {c.threshold or 'N/A'})")

            if r.value_trap_flags:
                lines.append(f"- **Trap Flags:** {'; '.join(r.value_trap_flags)}")
            lines.append("")

    # Avoid list with reasons
    if grades["D"]:
        lines.append("## Grade D — Avoid (Red Flags)")
        lines.append("")
        for r in grades["D"]:
            flags = "; ".join(r.value_trap_flags) if r.value_trap_flags else "Multiple check failures"
            lines.append(f"- **{r.ticker}** ({r.company_name}) — {flags}")
        lines.append("")

    content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # Also save as "latest" for easy access
    latest_path = os.path.join(THEME_REPORTS_DIR, f"{theme_slug}_LATEST.md")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Thematic report saved: {filepath}")
    return filepath


def save_technical_report(signals, tickers_label: str = "") -> str:
    """Save technical analysis results as markdown. Returns file path."""
    os.makedirs(TECH_REPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    label = tickers_label.replace(" ", "_").replace(",", "_")[:30] if tickers_label else "scan"
    filename = f"technical_{label}_{ts}.md"
    filepath = os.path.join(TECH_REPORTS_DIR, filename)

    lines = [
        f"# Technical Analysis",
        f"*Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        f"*Analyzed: {len(signals)} stocks*",
        "",
        "## Signals",
        "",
        "| Ticker | Action | Score | RSI | MACD | CPR | Volume | Trend |",
        "|--------|--------|-------|-----|------|-----|--------|-------|",
    ]

    for s in signals:
        if s is None:
            continue
        rsi = f"{s.rsi:.0f}" if s.rsi else "N/A"
        lines.append(
            f"| {s.ticker} | **{s.action}** | {s.score:+d} | "
            f"{rsi} ({s.rsi_signal}) | {s.macd_signal} | "
            f"{s.cpr_signal} | {s.volume_signal} | {s.trend} |"
        )
    lines.append("")

    # Detail for BUY/STRONG BUY
    buys = [s for s in signals if s and s.action in ("BUY", "STRONG BUY")]
    if buys:
        lines.append("## Buy Signals — Detail")
        lines.append("")
        for s in buys:
            lines.append(f"### {s.ticker} — {s.action} (score {s.score:+d})")
            lines.append(f"- **Close:** {s.close:,.2f}" if s.close else "")
            if s.change_1d is not None:
                lines.append(f"- **1D:** {s.change_1d:+.1f}% | 5D: {s.change_5d:+.1f}% | 20D: {s.change_20d:+.1f}%")
            lines.append(f"- **RSI:** {s.rsi:.1f}" if s.rsi else "")
            lines.append(f"- **MACD:** {s.macd_signal} (histogram: {s.macd_histogram:.2f})" if s.macd_histogram else "")
            if s.cpr_pivot:
                lines.append(f"- **CPR:** S1={s.cpr_s1:.2f} | BC={s.cpr_bc:.2f} | P={s.cpr_pivot:.2f} | TC={s.cpr_tc:.2f} | R1={s.cpr_r1:.2f}")
            if s.sma_50:
                lines.append(f"- **SMA50:** {s.sma_50:.2f} | SMA200: {s.sma_200:.2f}" if s.sma_200 else f"- **SMA50:** {s.sma_50:.2f}")
            lines.append(f"- **Reasons:** {'; '.join(s.reasons)}")
            lines.append("")

    content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Technical report saved: {filepath}")
    return filepath


def update_dashboard(theme_results: Optional[Dict] = None,
                      technical_signals: Optional[List] = None,
                      convergence_results: Optional[List] = None) -> str:
    """Update the master DASHBOARD.md with latest results from all screens.

    This is the single file to check for the current state of all screens.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    lines = [
        "# Stock Monitor — Dashboard",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
    ]

    # ── Thematic screens ─────────────────────────────────────────────────
    if theme_results:
        lines.append("## Thematic Screens")
        lines.append("")

        for theme_name, results in theme_results.items():
            grade_a = [r for r in results if r.grade == "A"]
            grade_b = [r for r in results if r.grade == "B"]
            grade_d = [r for r in results if r.grade == "D"]

            lines.append(f"### {theme_name}")
            lines.append(f"*{len(results)} stocks screened*")
            lines.append("")

            if grade_a:
                lines.append(f"**STRONG BUY ({len(grade_a)}):** " +
                             ", ".join(f"{r.ticker} ({r.checks_passed}/{r.checks_total})" for r in grade_a))
            if grade_b:
                high_b = [r for r in grade_b if r.exposure == "high"]
                other_b = [r for r in grade_b if r.exposure != "high"]
                if high_b:
                    lines.append(f"**BUY — High Exposure ({len(high_b)}):** " +
                                 ", ".join(f"{r.ticker}" for r in high_b))
                if other_b:
                    lines.append(f"**BUY — Other ({len(other_b)}):** " +
                                 ", ".join(f"{r.ticker}" for r in other_b))
            if grade_d:
                lines.append(f"**AVOID ({len(grade_d)}):** " +
                             ", ".join(f"{r.ticker} ({r.value_trap_label})" for r in grade_d))
            lines.append("")

    # ── Technical signals ────────────────────────────────────────────────
    if technical_signals:
        valid = [s for s in technical_signals if s is not None]
        buys = [s for s in valid if s.action in ("BUY", "STRONG BUY")]
        sells = [s for s in valid if s.action in ("SELL", "STRONG SELL")]

        lines.append("## Technical Signals")
        lines.append("")

        if buys:
            lines.append("| Ticker | Action | Score | RSI | MACD | CPR | Trend |")
            lines.append("|--------|--------|-------|-----|------|-----|-------|")
            for s in buys:
                rsi = f"{s.rsi:.0f}" if s.rsi else "N/A"
                lines.append(f"| **{s.ticker}** | {s.action} | {s.score:+d} | {rsi} | "
                             f"{s.macd_signal} | {s.cpr_signal} | {s.trend} |")
            lines.append("")
        else:
            lines.append("*No technical buy signals currently.*")
            lines.append("")

        if sells:
            lines.append(f"**Technical sells:** " +
                         ", ".join(f"{s.ticker} ({s.score:+d})" for s in sells))
            lines.append("")

    # ── Short-term convergence ───────────────────────────────────────────
    if convergence_results:
        converged = [r for r in convergence_results if r.converged]
        watches = [r for r in convergence_results if r.signal == "WATCH"]

        lines.append("## Short-Term Convergence")
        lines.append("")

        if converged:
            lines.append("| Ticker | Signal | Tech Score | Triggers | Reasons |")
            lines.append("|--------|--------|-----------|----------|---------|")
            for r in converged:
                reasons = "; ".join(r.reasons[:3])
                lines.append(f"| **{r.ticker}** | {r.signal} | {r.tech_score:+d} | "
                             f"{r.trigger_count} | {reasons} |")
            lines.append("")
        else:
            lines.append("*No convergence signals currently. Waiting for technical + fundamental alignment.*")
            lines.append("")

        if watches:
            lines.append(f"**Watchlist ({len(watches)}):** " +
                         ", ".join(f"{r.ticker}" for r in watches))
            lines.append("")

    # ── Report links ─────────────────────────────────────────────────────
    lines.append("## Report Archive")
    lines.append("")
    lines.append("- **Thematic screens:** `output/theme_screens/`")
    lines.append("- **Technical screens:** `output/technical_screens/`")
    lines.append("- **Short-term screens:** `output/shortterm_*.md`")
    lines.append("- **Valuation reports:** `reports/{TICKER}.md`")
    lines.append("- **Investment theses:** `output/analyses/{TICKER}_ANALYSIS.md`")
    lines.append("")

    content = "\n".join(lines)
    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Dashboard updated: {DASHBOARD_PATH}")
    return DASHBOARD_PATH
