"""
Management Integrity Report Writer
-----------------------------------
Assembles the final markdown integrity report from stored artifacts.
"""

import shutil
from pathlib import Path
from datetime import datetime

from config import INTEGRITY_REPORTS_DIR


def write_report(ticker, company_name, matrix, pattern_assessment,
                 from_year, to_year, base_dir):
    """
    Write the consolidated management integrity report.

    Args:
        ticker: NSE ticker symbol
        company_name: Full company name
        matrix: List of year-by-year comparison dicts
        pattern_assessment: AI-generated credibility analysis text
        from_year, to_year: Fiscal year range
        base_dir: Path to data/integrity/{TICKER}/

    Returns:
        Path to the output report file.
    """
    lines = []

    # Header
    date_str = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"# {company_name} — Management Integrity Report")
    lines.append(f"**Ticker:** {ticker} | **Period:** FY{from_year}–FY{to_year} | **Generated:** {date_str}")
    lines.append("")

    # Summary Scorecard
    total = len(matrix)
    quantitative = sum(1 for e in matrix
                       if e.get("guidance", {}).get("has_quantitative_target"))
    met_exceeded = sum(1 for e in matrix if e.get("verdict") in ("MET", "EXCEEDED"))
    missed = sum(1 for e in matrix if e.get("verdict") == "MISSED")
    score = f"{met_exceeded}/{quantitative} ({met_exceeded/quantitative*100:.0f}%)" if quantitative > 0 else "N/A (no quantitative guidance)"

    lines.append("---")
    lines.append("")
    lines.append("## Summary Scorecard")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Years Analyzed | {total} |")
    lines.append(f"| Quantitative Guidance Given | {quantitative} of {total} years |")
    lines.append(f"| Guidance Met/Exceeded | {met_exceeded} |")
    lines.append(f"| Guidance Missed | {missed} |")
    lines.append(f"| Integrity Score | {score} |")
    lines.append("")

    # Year-by-Year Analysis
    lines.append("---")
    lines.append("")
    lines.append("## Year-by-Year Analysis")

    for entry in matrix:
        fy = entry["fiscal_year"]
        g_fy = entry["guidance_from_fy"]
        g = entry.get("guidance") or {}
        a_mda = entry.get("actuals_mda") or {}
        a_scr = entry.get("actuals_screener") or {}

        lines.append("")
        lines.append(f"### FY{fy}")
        lines.append("")

        # What Management Said
        lines.append(f"**What Management Said (FY{g_fy} Annual Report):**")

        quotes = g.get("source_quotes", [])
        if quotes:
            for q in quotes[:2]:
                lines.append(f'> "{q}"')
            lines.append("")

        target = g.get("stated_target") or g.get("qualitative_outlook") or "No guidance available"
        lines.append(f"- **Target:** {target}")

        drivers = g.get("key_growth_drivers", [])
        if drivers:
            lines.append(f"- **Drivers cited:** {', '.join(drivers)}")

        tone = g.get("tone")
        if tone:
            lines.append(f"- **Tone:** {tone}")

        lines.append("")

        # What Actually Happened
        lines.append("**What Actually Happened:**")
        lines.append("")
        lines.append("| Metric | MD&A Reported | Screener Verified |")
        lines.append("|---|---|---|")

        rev_mda = _fmt_cr(a_mda.get("revenue_cr"))
        rev_scr = _fmt_cr(a_scr.get("revenue_cr"))
        lines.append(f"| Revenue | {rev_mda} | {rev_scr} |")

        growth_mda = _fmt_pct(a_mda.get("revenue_growth_pct"))
        growth_scr = _fmt_pct(a_scr.get("revenue_growth_pct"))
        lines.append(f"| Revenue Growth | {growth_mda} | {growth_scr} |")

        pat_mda = _fmt_cr(a_mda.get("pat_cr"))
        pat_scr = _fmt_cr(a_scr.get("pat_cr"))
        lines.append(f"| PAT | {pat_mda} | {pat_scr} |")

        lines.append("")

        # Verdict
        verdict = entry.get("verdict", "UNQUANTIFIED")
        lines.append(f"**Verdict: {verdict}**")
        lines.append("")

        commentary = entry.get("commentary", "")
        if commentary:
            # Extract just the verdict explanation from the commentary file
            # Commentary files have structured headers; we want the text after "## Verdict:"
            verdict_text = _extract_verdict_text(commentary)
            if verdict_text:
                lines.append(verdict_text)
            else:
                lines.append(commentary)
            lines.append("")

        # Reference links
        lines.append(
            f"*[Ref: guidance/{ticker}_guidance_FY{g_fy}.md | "
            f"actuals/{ticker}_actuals_FY{fy}.md | "
            f"commentary/{ticker}_compare_FY{fy}.md]*"
        )

        lines.append("")
        lines.append("---")

    # Promise vs Reality Table
    lines.append("")
    lines.append("## Revenue Growth: Promise vs Reality")
    lines.append("")
    lines.append("| FY | Guided Growth | Actual Growth | Verdict |")
    lines.append("|---|---|---|---|")

    for entry in matrix:
        fy = entry["fiscal_year"]
        g = entry.get("guidance") or {}

        if g.get("has_quantitative_target") and g.get("stated_target"):
            guided = g["stated_target"]
        elif g.get("qualitative_outlook"):
            guided = f'"{g["qualitative_outlook"]}"'
        else:
            guided = "—"

        actual = _fmt_pct(entry.get("actual_growth_pct"))
        verdict = entry.get("verdict", "—")
        lines.append(f"| {fy} | {guided} | {actual} | {verdict} |")

    # Pattern Assessment
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Pattern Assessment")
    lines.append("")
    if pattern_assessment:
        lines.append(pattern_assessment)
    else:
        lines.append("*Insufficient data for pattern assessment.*")

    # Write to both locations
    report_text = "\n".join(lines) + "\n"

    # Primary: data/integrity/{TICKER}/
    primary_path = base_dir / f"{ticker}_integrity_report.md"
    primary_path.write_text(report_text, encoding="utf-8")

    # Copy to output/integrity_reports/
    output_dir = Path(INTEGRITY_REPORTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ticker}_integrity.md"
    shutil.copy2(primary_path, output_path)

    return str(output_path)


# ── Formatting helpers ───────────────────────────────────────────────────────

def _extract_verdict_text(commentary_md):
    """Extract just the explanation text after the Verdict line in commentary markdown."""
    import re
    # Find text after "## Verdict: ..." heading
    match = re.search(r"## Verdict:.*?\n(.+?)(?:\n#|\Z)", commentary_md, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _fmt_cr(value):
    if value is None:
        return "—"
    try:
        return f"Rs {float(value):,.0f} Cr"
    except (ValueError, TypeError):
        return str(value)


def _fmt_pct(value):
    if value is None:
        return "—"
    try:
        return f"{float(value)}%"
    except (ValueError, TypeError):
        return str(value)
