"""
Management Integrity Analyzer
-----------------------------
Pipeline: download annual reports → find/flag missing MD&A context files →
read cached guidance & actuals JSONs → build integrity matrix → assemble report.

The MD&A context markdown (8-block structured file) is the FOUNDATION LAYER.
This module never touches PDFs directly. It reads from MD&A context files
that are created by /extract-sections in conversation.

If MD&A context files are missing, the pipeline stops and tells the user
which years need extraction via /extract-sections.

Usage (from Claude Code conversation):
    python run.py integrity TCS
    python run.py integrity TCS --from-year 2021 --to-year 2025
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime

from config import (
    ANNUAL_REPORTS_DIR, INTEGRITY_DIR, INTEGRITY_REPORTS_DIR,
    BASE_DIR,
)
from shared.utils import logger


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_dirs(ticker):
    """Create the full integrity directory structure for a ticker."""
    base = Path(INTEGRITY_DIR) / ticker
    for sub in ["guidance", "actuals", "commentary"]:
        (base / sub).mkdir(parents=True, exist_ok=True)
    Path(INTEGRITY_REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    return base


# ── Step 1: Auto-download missing annual reports ────────────────────────────

def _ensure_annual_reports(ticker, from_year, to_year):
    """Download missing annual reports for the ticker."""
    ar_dir = Path(ANNUAL_REPORTS_DIR) / ticker
    missing_years = []
    for year in range(from_year, to_year + 1):
        pdf = ar_dir / f"{ticker}_AnnualReport_FY{year}.pdf"
        if not pdf.exists():
            missing_years.append(year)

    if not missing_years:
        logger.info(f"  All annual reports exist for {ticker} (FY{from_year}-FY{to_year})")
        return

    logger.info(f"  Downloading missing annual reports for {ticker}: FY{missing_years}")
    from red_flag.downloader import run as download_run
    download_run(
        companies=[ticker],
        from_year=min(missing_years),
        to_year=max(missing_years),
    )


# ── Step 2: Find MD&A context files (the foundation layer) ──────────────────

def _find_mda_context_files(ticker, from_year, to_year):
    """
    Find existing MD&A context markdown files.
    These are the structured 8-block files created by /extract-sections.
    Returns {year: Path}, list_of_missing_years.
    """
    ar_dir = Path(ANNUAL_REPORTS_DIR) / ticker
    if not ar_dir.exists():
        return {}, list(range(from_year, to_year + 1))

    # Match both naming patterns:
    #   {TICKER}_MDA_Context_FY{YEAR}.md  (older)
    #   {TICKER}_MDA_FY{YEAR}_context.md  (newer, from mda_agent.py)
    pattern = re.compile(
        rf"{re.escape(ticker)}_MDA_(?:Context_)?FY(\d{{4}})_?(?:context)?\.md",
        re.IGNORECASE,
    )

    found = {}
    for f in ar_dir.iterdir():
        m = pattern.match(f.name)
        if m:
            year = int(m.group(1))
            if from_year <= year <= to_year:
                found[year] = f

    missing = [y for y in range(from_year, to_year + 1) if y not in found]
    return found, missing


# ── Step 3: Check for cached guidance + actuals ──────────────────────────────

def _load_cached_extractions(base_dir, ticker, from_year, to_year):
    """Load guidance and actuals from cached JSON files."""
    guidance_by_year = {}
    actuals_by_year = {}
    missing_years = []

    for year in range(from_year, to_year + 1):
        g_path = base_dir / "guidance" / f"{ticker}_guidance_FY{year}.json"
        a_path = base_dir / "actuals" / f"{ticker}_actuals_FY{year}.json"

        if g_path.exists() and a_path.exists():
            with open(g_path, "r", encoding="utf-8") as f:
                guidance_by_year[year] = json.load(f)
            with open(a_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
                actuals_by_year[year] = cached.get("mda", cached)
        else:
            missing_years.append(year)

    return guidance_by_year, actuals_by_year, missing_years


# ── Step 4: Fetch Screener.in actuals ────────────────────────────────────────

def _fetch_screener_actuals(ticker, from_year, to_year):
    """Fetch actual financials from Screener.in. Returns {year: dict}, company_name."""
    from shared.scraper import ScreenerScraper
    from shared.data_parser import parse_company_page, get_annual_values

    scraper = ScreenerScraper()
    html, variant = scraper.fetch_company_html(ticker)
    if not html:
        logger.warning(f"  Could not fetch Screener data for {ticker}")
        return {}, None

    data = parse_company_page(html, ticker)
    company_name = data.get("name", ticker)

    sales_pairs = get_annual_values(data, "profit_loss", "Sales")
    pat_pairs = get_annual_values(data, "profit_loss", "Net Profit")

    revenue_by_year = {}
    for year_str, value in sales_pairs:
        m = re.search(r"(\d{4})", year_str)
        if m:
            revenue_by_year[int(m.group(1))] = value

    pat_by_year = {}
    for year_str, value in pat_pairs:
        m = re.search(r"(\d{4})", year_str)
        if m:
            pat_by_year[int(m.group(1))] = value

    result = {}
    for year in range(from_year, to_year + 1):
        rev = revenue_by_year.get(year)
        prev_rev = revenue_by_year.get(year - 1)
        growth = None
        if rev is not None and prev_rev and prev_rev > 0:
            growth = round((rev - prev_rev) / prev_rev * 100, 1)

        result[year] = {
            "revenue_cr": rev,
            "revenue_growth_pct": growth,
            "pat_cr": pat_by_year.get(year),
        }

    return result, company_name


# ── Step 5: Build integrity matrix ───────────────────────────────────────────

def _determine_verdict(guidance, actual_growth):
    """Compare guidance to actual growth and return verdict."""
    if not guidance or not guidance.get("has_quantitative_target"):
        return "UNQUANTIFIED"
    if actual_growth is None:
        return "UNQUANTIFIED"

    low = guidance.get("target_low_pct")
    high = guidance.get("target_high_pct")

    if low is not None and high is None:
        high = low
    if high is not None and low is None:
        low = high
    if low is None and high is None:
        return "UNQUANTIFIED"

    if actual_growth > high:
        return "EXCEEDED"
    elif actual_growth >= low:
        return "MET"
    else:
        return "MISSED"


def _build_matrix(guidance_by_year, actuals_by_year, screener_by_year, from_year, to_year):
    """
    Build the integrity matrix.
    FY{N-1} guidance is compared to FY{N} actuals.
    """
    matrix = []
    for year in range(from_year + 1, to_year + 1):
        guidance_year = year - 1
        guidance = guidance_by_year.get(guidance_year)
        actuals_mda = actuals_by_year.get(year)
        actuals_scr = screener_by_year.get(year, {})

        actual_growth = actuals_scr.get("revenue_growth_pct")
        if actual_growth is None and actuals_mda:
            actual_growth = actuals_mda.get("revenue_growth_pct")

        verdict = _determine_verdict(guidance, actual_growth)

        matrix.append({
            "fiscal_year": year,
            "guidance_from_fy": guidance_year,
            "guidance": guidance,
            "actuals_mda": actuals_mda,
            "actuals_screener": actuals_scr,
            "actual_growth_pct": actual_growth,
            "verdict": verdict,
        })

    return matrix


# ── Step 6: Load cached commentary ───────────────────────────────────────────

def _load_commentary(base_dir, ticker, matrix):
    """Load per-year commentary and pattern assessment from cached files."""
    for entry in matrix:
        fy = entry["fiscal_year"]
        cp = base_dir / "commentary" / f"{ticker}_compare_FY{fy}.md"
        if cp.exists():
            entry["commentary"] = cp.read_text(encoding="utf-8")

    pattern_assessment = ""
    existing_report = base_dir / f"{ticker}_integrity_report.md"
    if existing_report.exists():
        report_text = existing_report.read_text(encoding="utf-8")
        pa_match = re.search(r"## Pattern Assessment\n\n(.+)", report_text, re.DOTALL)
        if pa_match:
            pattern_assessment = pa_match.group(1).strip()

    return pattern_assessment


# ── Storage helpers (called by Claude Code in conversation) ──────────────────

def store_guidance(base_dir, ticker, year, guidance):
    """Store guidance as JSON and human-readable markdown."""
    g_dir = Path(base_dir) / "guidance"
    g_dir.mkdir(parents=True, exist_ok=True)

    json_path = g_dir / f"{ticker}_guidance_FY{year}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(guidance, f, indent=2)

    md_path = g_dir / f"{ticker}_guidance_FY{year}.md"
    target = guidance.get("stated_target") or "No quantitative target provided"
    low = guidance.get("target_low_pct")
    high = guidance.get("target_high_pct")
    range_line = ""
    if low is not None or high is not None:
        range_line = f"\n- Low: {low}% | High: {high}%"

    drivers = guidance.get("key_growth_drivers", [])
    drivers_md = "\n".join(f"- {d}" for d in drivers) if drivers else "- Not specified"

    quotes = guidance.get("source_quotes", [])
    quotes_md = "\n".join(f'> "{q}"' for q in quotes) if quotes else "> No verbatim quotes captured"

    md_content = f"""# {ticker} — Revenue Guidance | FY{year}
**Source:** {ticker}_MDA_FY{year}.md, Block 7

## Quantitative Target
{target}{range_line}

## Qualitative Outlook
{guidance.get("qualitative_outlook", "Not available")}

## Key Growth Drivers
{drivers_md}

## Management Tone
{guidance.get("tone", "Not assessed")}

## Verbatim Quotes
{quotes_md}
"""
    md_path.write_text(md_content, encoding="utf-8")
    return json_path, md_path


def store_actuals(base_dir, ticker, year, actuals_mda, actuals_screener):
    """Store actuals as JSON and human-readable markdown."""
    a_dir = Path(base_dir) / "actuals"
    a_dir.mkdir(parents=True, exist_ok=True)

    combined = {"mda": actuals_mda, "screener": actuals_screener}

    json_path = a_dir / f"{ticker}_actuals_FY{year}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    md_path = a_dir / f"{ticker}_actuals_FY{year}.md"

    def fmt(v, suffix=""):
        if v is None:
            return "—"
        if suffix == "%":
            return f"{v}{suffix}"
        return f"Rs {v:,.0f} Cr" if isinstance(v, (int, float)) else str(v)

    mda = actuals_mda or {}
    scr = actuals_screener or {}

    md_content = f"""# {ticker} — Reported Actuals | FY{year}
**Sources:** MD&A Block 2, Screener.in

| Metric | MD&A Reported | Screener Verified |
|---|---|---|
| Revenue | {fmt(mda.get("revenue_cr"))} | {fmt(scr.get("revenue_cr"))} |
| Revenue Growth | {fmt(mda.get("revenue_growth_pct"), "%")} | {fmt(scr.get("revenue_growth_pct"), "%")} |
| PAT | {fmt(mda.get("pat_cr"))} | {fmt(scr.get("pat_cr"))} |
| EBITDA Margin | {fmt(mda.get("ebitda_margin_pct"), "%")} | — |
"""
    md_path.write_text(md_content, encoding="utf-8")
    return json_path, md_path


# ── Main Pipeline ────────────────────────────────────────────────────────────

def run(ticker, from_year=None, to_year=None, fresh=False):
    """
    Run the management integrity pipeline for a ticker.

    Flow:
        1. Download missing annual reports (automated)
        2. Check for MD&A context files — STOP if missing (user runs /extract-sections)
        3. Read cached guidance/actuals JSONs — STOP if missing (user creates them)
        4. Fetch Screener.in actuals (automated)
        5. Build integrity matrix (automated)
        6. Load cached commentary (automated)
        7. Assemble final report (automated)

    Returns:
        Path to the generated integrity report, or None if prerequisites missing.
    """
    ticker = ticker.strip().upper()
    current_year = datetime.now().year
    if from_year is None:
        from_year = current_year - 5
    if to_year is None:
        to_year = current_year

    logger.info(f"{'='*60}")
    logger.info(f"Management Integrity Agent — {ticker}")
    logger.info(f"Period: FY{from_year} to FY{to_year}")
    logger.info(f"{'='*60}")

    base_dir = _ensure_dirs(ticker)

    # Step 1: Ensure annual reports downloaded
    logger.info("Step 1: Checking annual reports...")
    _ensure_annual_reports(ticker, from_year, to_year)

    # Step 2: Check for MD&A context files (the foundation)
    logger.info("Step 2: Checking MD&A context files...")
    mda_files, mda_missing = _find_mda_context_files(ticker, from_year, to_year)

    if mda_missing:
        ar_dir = Path(ANNUAL_REPORTS_DIR) / ticker
        logger.info(f"")
        logger.info(f"  MD&A context files MISSING for: FY{mda_missing}")
        logger.info(f"  Available PDFs:")
        for year in mda_missing:
            pdf = ar_dir / f"{ticker}_AnnualReport_FY{year}.pdf"
            if pdf.exists():
                logger.info(f"    {pdf}")
        logger.info(f"")
        logger.info(f"  ACTION: Run /extract-sections on each missing PDF to create")
        logger.info(f"  the structured 8-block markdown. These are the foundation")
        logger.info(f"  layer — all analysis modules read from them.")
        logger.info(f"")
        logger.info(f"  Then re-run: python run.py integrity {ticker}")
        return None

    logger.info(f"  MD&A context files found for: FY{sorted(mda_files.keys())}")

    # Step 3: Check for cached guidance + actuals
    logger.info("Step 3: Checking cached extractions...")
    guidance_by_year, actuals_by_year, extraction_missing = _load_cached_extractions(
        base_dir, ticker, from_year, to_year
    )

    if extraction_missing and not fresh:
        logger.info(f"")
        logger.info(f"  Guidance/actuals extractions MISSING for: FY{extraction_missing}")
        logger.info(f"  MD&A context files to read from:")
        for year in extraction_missing:
            if year in mda_files:
                logger.info(f"    {mda_files[year]}")
        logger.info(f"")
        logger.info(f"  ACTION: Read Block 2 + Block 7 from each MD&A context file")
        logger.info(f"  and create guidance + actuals JSON files at:")
        logger.info(f"    {base_dir / 'guidance'}/")
        logger.info(f"    {base_dir / 'actuals'}/")
        logger.info(f"")
        logger.info(f"  Then re-run: python run.py integrity {ticker}")
        return None

    logger.info(f"  All extractions cached for FY{sorted(guidance_by_year.keys())}")

    # Step 4: Fetch Screener.in actuals
    logger.info("Step 4: Fetching Screener.in actuals...")
    screener_by_year, company_name = _fetch_screener_actuals(ticker, from_year, to_year)
    if not company_name:
        company_name = ticker

    # Step 5: Build integrity matrix
    logger.info("Step 5: Building integrity matrix...")
    matrix = _build_matrix(guidance_by_year, actuals_by_year, screener_by_year,
                           from_year, to_year)

    # Step 6: Load cached commentary
    logger.info("Step 6: Loading commentary...")
    pattern_assessment = _load_commentary(base_dir, ticker, matrix)

    missing_commentary = [e["fiscal_year"] for e in matrix if "commentary" not in e]
    if missing_commentary:
        logger.info(f"  Commentary missing for: FY{missing_commentary}")
        logger.info(f"  Commentary files go to: {base_dir / 'commentary'}/")

    # Step 7: Write final report
    logger.info("Step 7: Writing integrity report...")
    from management_integrity.report_writer import write_report

    report_path = write_report(
        ticker=ticker,
        company_name=company_name,
        matrix=matrix,
        pattern_assessment=pattern_assessment,
        from_year=from_year,
        to_year=to_year,
        base_dir=base_dir,
    )

    logger.info(f"{'='*60}")
    logger.info(f"Done: {report_path}")
    logger.info(f"Document library: {base_dir}")
    logger.info(f"{'='*60}")

    return report_path
