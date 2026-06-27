"""Narrative Generator — uses Claude API to interpret crunched financial data.

This is the intelligence layer. The data_cruncher computes verified numbers;
this module sends them to Claude to produce analyst-quality interpretation:
    - ROCE driver identification and sustainability assessment
    - Revenue & cash flow integrity verdict
    - Valuation positioning with bear/base cases
    - Consolidated analyst take

Returns structured sections that the builder interleaves with data tables.
"""

import os

from shared.utils import logger

# Load .env if available (for ANTHROPIC_API_KEY)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MODEL = "claude-sonnet-4-6"
SECTION_MARKER = "===SECTION==="


def _n(v, fmt=",.0f"):
    """Format number for prompt context."""
    if v is None:
        return "\u2014"
    try:
        return f"{v:{fmt}}"
    except (ValueError, TypeError):
        return str(v)


def _dupont_text(dupont):
    if not dupont:
        return "No DuPont data available.\n"
    lines = ["| Year | EBIT (Cr) | Cap Emp (Cr) | ROCE% | EBIT Mgn% | Asset Turn | D/E |"]
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for d in dupont:
        lines.append(
            f"| {d['year']} | {_n(d.get('ebit'))} | {_n(d.get('cap_employed'))} "
            f"| {_n(d.get('roce_pct'), '.1f')} | {_n(d.get('ebit_margin_pct'), '.1f')} "
            f"| {_n(d.get('asset_turnover'), '.2f')}x | {_n(d.get('de_ratio'), '.2f')} |"
        )
    return "\n".join(lines)


def _cf_text(cq):
    if not cq:
        return "No cash flow data available.\n"
    lines = ["| Year | PAT (Cr) | CFO (Cr) | EBITDA (Cr) | CFO/PAT | FCF (Cr) | FCF/PAT |"]
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for c in cq:
        lines.append(
            f"| {c['year']} | {_n(c.get('pat'))} | {_n(c.get('cfo'))} "
            f"| {_n(c.get('ebitda'))} | {_n(c.get('cfo_pat'), '.2f')} "
            f"| {_n(c.get('fcf'))} | {_n(c.get('fcf_pat'), '.2f')} |"
        )
    return "\n".join(lines)


def _rq_text(rq):
    if not rq:
        return "No revenue quality data available.\n"
    lines = ["| Year | Sales Gr% | Debtor Days |"]
    lines.append("|---|---:|---:|")
    for r in rq:
        sg = f"{r['sales_growth']:+.1f}%" if r.get("sales_growth") is not None else "\u2014"
        dd = f"{r['debtor_days']:.0f}" if r.get("debtor_days") is not None else "\u2014"
        lines.append(f"| {r['year']} | {sg} | {dd} |")
    return "\n".join(lines)


def _val_text(vs, multiples, key_ratios):
    """Build valuation context for the prompt."""
    lines = []

    lines.append("Current Multiples:")
    lines.append(f"  P/E: {_n(multiples.get('pe'), '.1f')}x")
    lines.append(f"  EV/EBITDA: {_n(multiples.get('ev_ebitda'), '.1f')}x")
    lines.append(f"  P/FCF: {_n(multiples.get('p_fcf'), '.1f')}x")
    lines.append(f"  P/Sales: {_n(multiples.get('p_sales'), '.2f')}x")
    lines.append(f"  P/Book: {_n(multiples.get('pb'), '.1f')}x")
    lines.append(f"  FCF Yield: {_n(multiples.get('fcf_yield'), '.2f')}%")

    lines.append(f"\nValuation Engine Verdict: {vs.verdict}")
    if vs.composite_iv:
        lines.append(f"  Weighted IV: \u20b9{vs.composite_iv:,.2f}")
    if vs.median_iv:
        lines.append(f"  Median IV: \u20b9{vs.median_iv:,.2f}")
    if vs.upside_pct is not None:
        lines.append(f"  Upside: {vs.upside_pct * 100:+.1f}%")
    lines.append(f"  Methods above CMP: {vs.methods_above_cmp}/{len(vs.results)}")

    if vs.pe_5yr_avg:
        lines.append(f"\nHistorical P/E: Current {vs.pe_current:.1f}x, "
                      f"5Y Avg {vs.pe_5yr_avg:.1f}x, "
                      f"Range {vs.pe_5yr_low:.1f}\u2013{vs.pe_5yr_high:.1f}x, "
                      f"Position: {vs.pe_position}")

    lines.append("\nIndividual Methods:")
    for r in vs.results:
        iv = f"\u20b9{r.intrinsic_value:,.2f}" if r.intrinsic_value else "N/A"
        lines.append(f"  {r.method}: {iv} (wt {r.weight:.0%}) \u2014 {r.notes}")

    for key, label in [
        ("sales_cagr_5y", "5Y Sales CAGR"),
        ("profit_cagr_5y", "5Y Profit CAGR"),
        ("fcf_cagr_5y", "5Y FCF CAGR"),
    ]:
        v = key_ratios.get(key)
        lines.append(f"  {label}: {v * 100:.1f}%" if v is not None else f"  {label}: N/A")

    return "\n".join(lines)


def generate_narrative(ticker, name, sector, industry, crunched, valuation_summary):
    """Call Claude API to produce analytical narrative sections.

    Returns dict with keys: module_a, module_b, module_c, summary.
    Falls back to placeholder text if API is unavailable.
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception as e:
        logger.warning(f"Claude API unavailable ({e}). Using placeholder narrative.")
        return _placeholder(ticker, valuation_summary)

    snap = crunched["snapshot"]
    kr = crunched["key_ratios"]

    aggregates = (
        f"CMP: \u20b9{_n(snap['cmp'], ',.2f')}, "
        f"MCap: \u20b9{_n(snap['market_cap'])} Cr, "
        f"EV: \u20b9{_n(snap['ev'])} Cr, "
        f"EPS: \u20b9{_n(snap['eps'], '.1f')}\n"
        f"ROE: {_n(snap.get('roe'), '.1f')}%, "
        f"ROCE: {_n(snap.get('roce'), '.1f')}%, "
        f"D/E: {_n(snap.get('de'), '.2f')}\n"
        f"Cumulative CFO/PAT: {_n(kr.get('cumulative_cfo_pat'), '.2f')}x, "
        f"FCF Yield: {_n(kr.get('fcf_yield'), '.2f')}%, "
        f"Promoter: {_n(snap.get('promoter_holding'), '.1f')}%"
    )

    trap_text = f"Value Trap: {valuation_summary.value_trap_label or 'CLEAN'}"
    if valuation_summary.value_trap_flags:
        trap_text += "\nFlags: " + "; ".join(valuation_summary.value_trap_flags)

    system_prompt = (
        f"You are a senior equity research analyst at a top Indian brokerage. "
        f"You write deep-dive reports for institutional investors.\n\n"
        f"Company: {name} ({ticker})\n"
        f"Sector: {sector} | Industry: {industry}\n\n"
        f"CRITICAL: All numbers below are pre-computed and verified. "
        f"Reference them exactly. Do NOT invent financial figures.\n\n"
        f"Write concisely. Be specific with numbers. Flag concerns as clearly as strengths. "
        f"No generic boilerplate."
    )

    user_prompt = (
        f"Write analytical commentary for {name} ({ticker}). "
        f"Use ONLY the data below.\n\n"
        f"### Key Metrics\n{aggregates}\n\n"
        f"### DuPont ROCE Decomposition\n{_dupont_text(crunched['dupont'])}\n\n"
        f"### Revenue Quality\n{_rq_text(crunched['revenue_quality'])}\n\n"
        f"### Cash Flow Quality\n{_cf_text(crunched['cashflow_quality'])}\n\n"
        f"### Valuation\n{_val_text(valuation_summary, crunched['valuation_multiples'], kr)}\n\n"
        f"### {trap_text}\n\n"
        f"---\n\n"
        f"Write FOUR sections separated by the exact marker '{SECTION_MARKER}' "
        f"on its own line between each section.\n\n"
        f"**Section 1 — ROCE Analysis:**\n"
        f"- Identify PRIMARY driver (margin vs asset turnover vs leverage). "
        f"Compare first-year vs last-year values.\n"
        f"- Note any inflection years with likely cause.\n"
        f"- Rate sustainability: IMPROVING, STABLE, MODERATING, or DECLINING.\n"
        f"- 2-3 concise paragraphs.\n\n"
        f"**Section 2 — Revenue & Cash Flow Integrity:**\n"
        f"- Flag debtor days spikes or trends.\n"
        f"- Assess cumulative CFO/PAT (>1.0 = clean, <0.8 = concerning).\n"
        f"- Comment on FCF yield and FCF/PAT trend.\n"
        f"- Verdict: CLEAN, MODERATE CONCERN, or RED FLAG.\n"
        f"- 2-3 paragraphs.\n\n"
        f"**Section 3 — Valuation Analysis:**\n"
        f"- Position vs weighted IV from valuation engine.\n"
        f"- Bear case (specific P/E + earnings = price).\n"
        f"- Base case (specific growth + multiple = price).\n"
        f"- Verdict: what should an investor do?\n"
        f"- 2-3 paragraphs.\n\n"
        f"**Section 4 — Consolidated Summary:**\n"
        f"- 3-row markdown table: | Module | Finding | Status |\n"
        f"- 'Analyst Take' paragraph: 3-4 bullet points of key non-obvious insights.\n\n"
        f"Return ONLY the four sections with markers between them. No preamble."
    )

    logger.info(f"  Calling Claude API for {ticker} narrative...")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
    except Exception as e:
        logger.error(f"  Claude API call failed: {e}")
        return _placeholder(ticker, valuation_summary)

    return _parse_sections(raw)


def _parse_sections(raw_text):
    """Split Claude's response into four sections using the marker."""
    parts = raw_text.split(SECTION_MARKER)
    # Clean up whitespace
    parts = [p.strip() for p in parts if p.strip()]

    return {
        "module_a": parts[0] if len(parts) > 0 else "",
        "module_b": parts[1] if len(parts) > 1 else "",
        "module_c": parts[2] if len(parts) > 2 else "",
        "summary": parts[3] if len(parts) > 3 else "",
    }


def _placeholder(ticker, vs):
    """Fallback when Claude API is unavailable."""
    verdict = vs.verdict if vs else "N/A"
    upside = f"{vs.upside_pct * 100:+.1f}%" if vs and vs.upside_pct else "N/A"
    return {
        "module_a": f"*ROCE analysis pending — Claude API unavailable.*",
        "module_b": f"*Revenue & cash flow integrity analysis pending.*",
        "module_c": (f"**Valuation Engine Verdict: {verdict}** (Upside: {upside})\n\n"
                     f"*Detailed narrative pending — Claude API unavailable.*"),
        "summary": (f"| Module | Finding | Status |\n|---|---|---|\n"
                    f"| ROCE | Pending | \u2014 |\n"
                    f"| Integrity | Pending | \u2014 |\n"
                    f"| Valuation | {verdict} | {upside} |\n"),
    }
