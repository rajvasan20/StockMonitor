"""Generate per-company markdown valuation reports — sector-aware."""

import os
from datetime import datetime
from config import REPORTS_DIR
from shared.data_parser import (
    get_ratio, get_cmp, get_value_series, get_latest_annual,
    get_ttm_value, get_promoter_holding, get_pb_ratio,
    get_debt_to_equity,
)
from shared.utils import format_inr, format_pct, logger, cagr


def write_report(ticker, data, summary):
    """Write a detailed markdown report for a single company."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filepath = os.path.join(REPORTS_DIR, f"{ticker}.md")

    lines = []
    name = data.get("name", ticker)
    cmp = get_cmp(data)

    # Header
    lines.append(f"# {name} ({ticker})")
    lines.append(f"**Analysis Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Sector:** {summary.sector or 'N/A'} | **Industry:** {summary.industry or 'N/A'}")
    lines.append(f"**Verdict:** {summary.verdict}")
    lines.append("")

    # Snapshot — with computed fields
    pb = get_pb_ratio(data)
    de = get_debt_to_equity(data)
    if de is None:
        de_raw = get_ratio(data, "Debt to equity")
        de_str = f"{de_raw:.2f}" if de_raw is not None else "N/A"
    else:
        de_str = f"{de:.2f}"
    promoter = get_promoter_holding(data)

    lines.append("## Current Snapshot")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    snapshot_items = [
        ("Current Price", f"\u20b9{cmp:,.2f}" if cmp else "N/A"),
        ("Market Cap", data.get("top_ratios", {}).get("Market Cap", "N/A")),
        ("P/E Ratio", data.get("top_ratios", {}).get("Stock P/E", "N/A")),
        ("P/B Ratio", f"{pb:.2f}" if pb else "N/A"),
        ("Book Value", data.get("top_ratios", {}).get("Book Value", "N/A")),
        ("ROE %", data.get("top_ratios", {}).get("ROE", "N/A")),
        ("ROCE %", data.get("top_ratios", {}).get("ROCE", "N/A")),
        ("Debt/Equity", de_str),
        ("Dividend Yield %", data.get("top_ratios", {}).get("Dividend Yield", "N/A")),
        ("Promoter Holding %", f"{promoter:.1f}" if promoter else "N/A"),
    ]
    for metric, val in snapshot_items:
        lines.append(f"| {metric} | {val} |")
    lines.append("")

    # Historical P/E Context
    if summary.pe_5yr_avg is not None:
        lines.append("## Historical P/E Context")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Current P/E | {summary.pe_current:.1f}x |")
        lines.append(f"| 5-Year Avg P/E | {summary.pe_5yr_avg:.1f}x |")
        lines.append(f"| 5-Year Low P/E | {summary.pe_5yr_low:.1f}x |")
        lines.append(f"| 5-Year High P/E | {summary.pe_5yr_high:.1f}x |")
        lines.append(f"| Position | {summary.pe_position} |")
        lines.append("")

    # 5-Year Financial Summary
    lines.append("## Financial Summary (Last 5 Years)")
    lines.append("")
    sales = get_value_series(data, "profit_loss", "Sales", n_years=5)
    profits = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    if sales:
        lines.append(f"- **Sales CAGR:** {_calc_cagr_str(sales)}")
    if profits:
        lines.append(f"- **Profit CAGR:** {_calc_cagr_str(profits)}")
    lines.append("")

    # Valuation Results Table — with weights
    lines.append("## Valuation Methods")
    lines.append("")
    lines.append("| # | Method | Intrinsic Value | vs CMP | Weight | Confidence | Notes |")
    lines.append("|---|--------|----------------|--------|--------|------------|-------|")

    for i, r in enumerate(summary.results, 1):
        iv_str = f"\u20b9{r.intrinsic_value:,.2f}" if r.intrinsic_value else "N/A"
        if r.intrinsic_value and cmp and cmp > 0:
            diff = ((r.intrinsic_value / cmp) - 1) * 100
            vs_cmp = f"{diff:+.1f}%"
        else:
            vs_cmp = "-"
        weight_str = f"{r.weight*100:.0f}%"
        lines.append(f"| {i} | {r.method} | {iv_str} | {vs_cmp} | {weight_str} | {r.confidence} | {r.notes} |")
    lines.append("")

    # Value Trap Analysis
    lines.append("## Value Trap Analysis")
    lines.append("")
    lines.append(f"**Assessment:** {summary.value_trap_label} ({summary.value_trap_score} flag{'s' if summary.value_trap_score != 1 else ''})")
    lines.append("")
    if summary.value_trap_flags:
        for flag in summary.value_trap_flags:
            lines.append(f"- \u26a0\ufe0f {flag}")
    else:
        lines.append("- No value trap signals detected")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    if summary.composite_iv:
        lines.append(f"- **Weighted Intrinsic Value:** \u20b9{summary.composite_iv:,.2f}")
    if summary.median_iv:
        lines.append(f"- **Median Intrinsic Value:** \u20b9{summary.median_iv:,.2f} (reference)")
    if summary.upside_pct is not None:
        lines.append(f"- **Upside/Downside:** {summary.upside_pct*100:+.1f}%")
    lines.append(f"- **Methods suggesting undervaluation:** {summary.methods_above_cmp} of {len(summary.results)}")
    lines.append(f"- **Overall Verdict:** **{summary.verdict}**")
    if summary.is_bargain:
        lines.append(f"- **BARGAIN ALERT!** This stock appears significantly undervalued.")
    if summary.value_trap_label == "LIKELY TRAP":
        lines.append(f"- **VALUE TRAP WARNING:** Multiple red flags suggest this may be a value trap despite low valuation.")
    lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Report written: {filepath}")
    return filepath


def _calc_cagr_str(values):
    """Calculate CAGR from a list and return formatted string."""
    clean = [v for v in values if v is not None and v > 0]
    if len(clean) < 2:
        return "N/A"
    g = cagr(clean[0], clean[-1], len(clean) - 1)
    if g is not None:
        return f"{g*100:.1f}% ({len(clean)} years)"
    return "N/A"
