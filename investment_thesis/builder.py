"""Investment Thesis Builder — 5-Slider Report.

Orchestrates the full pipeline:
    1. Fetch company data from Screener.in
    2. Run the 5-method valuation engine
    3. Detect value traps
    4. Crunch thesis-specific metrics (deterministic)
    5. Generate analytical narrative via Claude API (intelligence layer)
    6. Assemble data tables + narrative into final markdown report
    7. Write to output/analyses/{TICKER}_ANALYSIS.md

Usage:
    python run.py thesis TCS
"""

import os
from datetime import datetime

from config import ANALYSES_DIR
from shared.utils import logger
from shared.scraper import ScreenerScraper
from shared.data_parser import parse_company_page
from universe_monitor.valuation_engine import run_all_valuations
from universe_monitor.value_trap import detect_value_traps
from investment_thesis.data_cruncher import crunch_all
from investment_thesis.narrative_generator import generate_narrative


# ── Table formatters ─────────────────────────────────────────────────────────

def _f(v, fmt=",.0f"):
    """Format number for markdown."""
    if v is None:
        return "\u2014"
    try:
        return f"{v:{fmt}}"
    except (ValueError, TypeError):
        return str(v)


def _snapshot_md(snap, sector, industry):
    return "\n".join([
        "| Metric | Value |",
        "|---|---|",
        f"| CMP | \u20b9{_f(snap['cmp'], ',.1f')} |",
        f"| Market Cap | \u20b9{_f(snap['market_cap'])} Cr |",
        f"| EV | \u20b9{_f(snap['ev'])} Cr |",
        f"| EPS | \u20b9{_f(snap['eps'], '.1f')} |",
        f"| P/E | {_f(snap['pe'], '.1f')}x |",
        f"| P/B | {_f(snap.get('pb'), '.1f')}x |",
        f"| ROE | {_f(snap.get('roe'), '.1f')}% |",
        f"| ROCE | {_f(snap.get('roce'), '.1f')}% |",
        f"| D/E | {_f(snap.get('de'), '.2f')} |",
        f"| Dividend Yield | {_f(snap.get('dividend_yield'), '.1f')}% |",
        f"| Promoter Holding | {_f(snap.get('promoter_holding'), '.1f')}% |",
        f"| Shares | {_f(snap['shares'], '.2f')} Cr |",
    ])


def _annual_table(rows, metrics, title):
    """Generic annual table builder.

    metrics: list of (display_label, dict_key, format_string)
    """
    if not rows:
        return f"No {title} data available."
    years = [r["year"] for r in rows]
    header = "| Metric | " + " | ".join(years) + " |"
    sep = "|---|" + "|".join(["---:" for _ in years]) + "|"
    lines = [header, sep]
    for label, key, fmt in metrics:
        vals = [_f(r.get(key), fmt) for r in rows]
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    return "\n".join(lines)


def _pl_md(pl):
    return _annual_table(pl, [
        ("Sales", "sales", ",.0f"),
        ("Operating Profit", "operating_profit", ",.0f"),
        ("OPM %", "opm_pct", ".1f"),
        ("Other Income", "other_income", ",.0f"),
        ("Depreciation", "depreciation", ",.0f"),
        ("Interest", "interest", ",.0f"),
        ("PBT", "pbt", ",.0f"),
        ("Tax %", "tax_pct", ".1f"),
        ("Net Profit", "pat", ",.0f"),
        ("EPS (\u20b9)", "eps", ".1f"),
    ], "P&L")


def _bs_md(bs):
    return _annual_table(bs, [
        ("Equity Capital", "equity_capital", ",.0f"),
        ("Reserves", "reserves", ",.0f"),
        ("Total Equity", "total_equity", ",.0f"),
        ("Borrowings", "borrowings", ",.0f"),
        ("Other Liabilities", "other_liabilities", ",.0f"),
        ("Net Block", "net_block", ",.0f"),
        ("CWIP", "cwip", ",.0f"),
        ("Investments", "investments", ",.0f"),
        ("Other Assets", "other_assets", ",.0f"),
    ], "Balance Sheet")


def _cf_md(cf):
    return _annual_table(cf, [
        ("CFO", "cfo", ",.0f"),
        ("CFI", "cfi", ",.0f"),
        ("CFF", "cff", ",.0f"),
        ("FCF", "fcf", ",.0f"),
    ], "Cash Flow")


def _quarterly_md(qtrs):
    if not qtrs:
        return "No quarterly data available."
    lines = [
        "| Quarter | Sales | Expenses | Op Profit | OPM% | PAT | PAT Mgn% |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for q in qtrs:
        lines.append(
            f"| {q['quarter']} "
            f"| {_f(q.get('sales'))} "
            f"| {_f(q.get('expenses'))} "
            f"| {_f(q.get('operating_profit'))} "
            f"| {_f(q.get('opm_pct'), '.1f')}% "
            f"| {_f(q.get('pat'))} "
            f"| {_f(q.get('pat_margin'), '.1f')}% |"
        )
    return "\n".join(lines)


def _dupont_md(dupont):
    if not dupont:
        return "Insufficient data for DuPont analysis."
    lines = [
        "| Year | EBIT | Cap Emp | ROCE% | EBIT Mgn% | Asset Turn | D/E | NFA Turn |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for d in dupont:
        lines.append(
            f"| {d['year']} "
            f"| {_f(d.get('ebit'))} "
            f"| {_f(d.get('cap_employed'))} "
            f"| {_f(d.get('roce_pct'), '.1f')}% "
            f"| {_f(d.get('ebit_margin_pct'), '.1f')}% "
            f"| {_f(d.get('asset_turnover'), '.2f')}x "
            f"| {_f(d.get('de_ratio'), '.2f')} "
            f"| {_f(d.get('nfa_turnover'), '.1f')}x |"
        )
    return "\n".join(lines)


def _cf_quality_md(cq):
    if not cq:
        return "Insufficient data."
    lines = [
        "| Year | PAT | CFO | EBITDA | CFO/PAT | CFO/EBITDA | FCF | FCF/PAT |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cq:
        lines.append(
            f"| {c['year']} "
            f"| {_f(c.get('pat'))} "
            f"| {_f(c.get('cfo'))} "
            f"| {_f(c.get('ebitda'))} "
            f"| {_f(c.get('cfo_pat'), '.2f')} "
            f"| {_f(c.get('cfo_ebitda'), '.2f')} "
            f"| {_f(c.get('fcf'))} "
            f"| {_f(c.get('fcf_pat'), '.2f')} |"
        )
    return "\n".join(lines)


def _rq_md(rq):
    if not rq:
        return "No revenue quality data."
    lines = [
        "| Year | Sales Gr% | Debtor Days |",
        "|---|---:|---:|",
    ]
    for r in rq:
        sg = f"{r['sales_growth']:+.1f}%" if r.get("sales_growth") is not None else "\u2014"
        dd = f"{r['debtor_days']:.0f}" if r.get("debtor_days") is not None else "\u2014"
        lines.append(f"| {r['year']} | {sg} | {dd} |")
    return "\n".join(lines)


def _valuation_methods_md(vs):
    """Valuation engine results table."""
    if not vs.results:
        return "No valuation results."
    lines = [
        "| # | Method | Intrinsic Value | vs CMP | Weight | Notes |",
        "|---|--------|----------------|--------|--------|-------|",
    ]
    for i, r in enumerate(vs.results, 1):
        if r.intrinsic_value:
            iv_str = f"\u20b9{r.intrinsic_value:,.2f}"
            diff = ((r.intrinsic_value / vs.cmp) - 1) * 100 if vs.cmp > 0 else 0
            vs_str = f"{diff:+.1f}%"
        else:
            iv_str = "N/A"
            vs_str = "\u2014"
        lines.append(
            f"| {i} | {r.method} | {iv_str} | {vs_str} "
            f"| {r.weight:.0%} | {r.notes} |"
        )
    return "\n".join(lines)


def _multiples_md(mult):
    return "\n".join([
        "| P/E | EV/EBITDA | P/FCF | P/Sales | P/Book | FCF Yield |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {_f(mult.get('pe'), '.1f')}x "
        f"| {_f(mult.get('ev_ebitda'), '.1f')}x "
        f"| {_f(mult.get('p_fcf'), '.1f')}x "
        f"| {_f(mult.get('p_sales'), '.2f')}x "
        f"| {_f(mult.get('pb'), '.1f')}x "
        f"| {_f(mult.get('fcf_yield'), '.2f')}% |",
    ])


def _key_ratios_md(kr):
    lines = []
    for key, label in [
        ("sales_cagr_5y", "5Y Sales CAGR"),
        ("profit_cagr_5y", "5Y Profit CAGR"),
        ("fcf_cagr_5y", "5Y FCF CAGR"),
        ("avg_roce_5y", "5Y Avg ROCE"),
        ("avg_roe_5y", "5Y Avg ROE"),
        ("cumulative_cfo_pat", "Cumulative CFO/PAT"),
        ("fcf_yield", "FCF Yield"),
    ]:
        v = kr.get(key)
        if v is not None:
            if "cagr" in key or "roce" in key or "roe" in key or "yield" in key:
                if "cagr" in key:
                    lines.append(f"- **{label}:** {v * 100:.1f}%")
                else:
                    lines.append(f"- **{label}:** {v:.1f}%")
            else:
                lines.append(f"- **{label}:** {v:.2f}x")
        else:
            lines.append(f"- **{label}:** N/A")
    return "\n".join(lines)


# ── Main builder ─────────────────────────────────────────────────────────────

def build_thesis(ticker):
    """Build a full investment thesis report for a ticker.

    Returns the output file path, or None on failure.
    """
    logger.info(f"{'=' * 50}")
    logger.info(f"Building investment thesis: {ticker}")
    logger.info(f"{'=' * 50}")

    # Step 1: Fetch
    scraper = ScreenerScraper()
    html, variant = scraper.fetch_company_html(ticker)
    if html is None:
        logger.error(f"{ticker}: Could not fetch from Screener.in")
        return None

    data = parse_company_page(html, ticker)
    if not data.get("top_ratios"):
        logger.error(f"{ticker}: No financial data parsed")
        return None

    name = data.get("name") or ticker
    sector = data.get("sector") or "Unknown"
    industry = data.get("industry") or "Unknown"
    logger.info(f"  Company: {name} | Sector: {sector}")

    # Step 2: Valuation engine
    logger.info(f"  Running valuation engine...")
    valuation = run_all_valuations(data)
    trap = detect_value_traps(data)
    valuation.value_trap_flags = trap.flags
    valuation.value_trap_score = trap.score
    valuation.value_trap_label = trap.label
    logger.info(f"  Verdict: {valuation.verdict}, "
                f"IV: \u20b9{valuation.composite_iv:,.0f}" if valuation.composite_iv
                else f"  Verdict: {valuation.verdict}")

    # Step 3: Crunch metrics
    logger.info(f"  Crunching thesis data...")
    crunched = crunch_all(data, valuation)

    # Step 4: AI narrative
    narrative = generate_narrative(
        ticker, name, sector, industry, crunched, valuation
    )

    # Step 5: Assemble report
    logger.info(f"  Assembling report...")
    date_str = datetime.now().strftime("%B %Y")
    kr = crunched["key_ratios"]

    # Value trap section
    trap_label = valuation.value_trap_label or "CLEAN"
    trap_lines = [f"**Assessment:** {trap_label} ({valuation.value_trap_score} flags)"]
    if valuation.value_trap_flags:
        for flag in valuation.value_trap_flags:
            trap_lines.append(f"- {flag}")
    else:
        trap_lines.append("- No value trap signals detected")
    trap_md = "\n".join(trap_lines)

    # Historical P/E section
    pe_md = ""
    if valuation.pe_5yr_avg:
        pe_md = "\n".join([
            "### Historical P/E Context",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Current P/E | {valuation.pe_current:.1f}x |",
            f"| 5-Year Avg P/E | {valuation.pe_5yr_avg:.1f}x |",
            f"| 5-Year Low P/E | {valuation.pe_5yr_low:.1f}x |",
            f"| 5-Year High P/E | {valuation.pe_5yr_high:.1f}x |",
            f"| Position | {valuation.pe_position} |",
            "",
        ])

    report = f"""# {name} \u2014 Equity Analysis
**Date:** {date_str}
**Source:** Screener.in
**Sector:** {sector} | **Industry:** {industry}
**All figures in INR Crores unless stated**

---

## Snapshot
{_snapshot_md(crunched['snapshot'], sector, industry)}

### Key Ratios
{_key_ratios_md(kr)}

{pe_md}
---

## Raw Data \u2014 Annual

### Profit & Loss
{_pl_md(crunched['annual_pl'])}

### Balance Sheet
{_bs_md(crunched['annual_bs'])}

### Cash Flow
{_cf_md(crunched['annual_cf'])}

---

## Quarterly P&L
{_quarterly_md(crunched['quarterly'])}

---

## MODULE A \u2014 ROCE Expansion Analysis

### DuPont Table
{_dupont_md(crunched['dupont'])}

{narrative['module_a']}

---

## MODULE B \u2014 Revenue & Cash Flow Integrity

### Revenue Quality
{_rq_md(crunched['revenue_quality'])}

### Cash Flow Quality
{_cf_quality_md(crunched['cashflow_quality'])}

{narrative['module_b']}

---

## MODULE C \u2014 Valuation Analysis

### Current Multiples
{_multiples_md(crunched['valuation_multiples'])}

### Valuation Engine Results
{_valuation_methods_md(valuation)}

{narrative['module_c']}

---

## Value Trap Analysis
{trap_md}

---

## Consolidated Summary
{narrative['summary']}
"""

    # Step 6: Write
    os.makedirs(ANALYSES_DIR, exist_ok=True)
    output_path = os.path.join(ANALYSES_DIR, f"{ticker}_ANALYSIS.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"  Thesis written: {output_path}")
    return output_path
