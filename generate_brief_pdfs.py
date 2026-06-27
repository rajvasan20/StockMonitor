"""Generate polished PDFs from sector intelligence briefs."""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from reports.pdf_generator import (
    _load_css, _build_cover, _build_exec_summary, _build_disclaimer,
    _md_to_html_body, _wrap_full_html, _render_pdf,
)
from datetime import datetime
from pathlib import Path


BRIEFS_DIR = Path("data/annual_reports/industry_context/briefs")
OUTPUT_DIR = Path("output/reports_store/industry")


def _parse_brief_exec_summary(md_text):
    """Extract exec summary bullets from a sector intelligence brief."""
    bullets = []

    # Extract companies line
    companies = re.search(r"\*\*Companies:\*\*\s*(.+)", md_text)
    if companies:
        names = [c.strip() for c in companies.group(1).split(",")]
        bullets.append(f"<strong>{len(names)} companies</strong> analyzed: {companies.group(1).strip()}")

    # Count consensus themes
    consensus = re.findall(r"^\d+\.\s+\*\*(.+?)\*\*", md_text, re.MULTILINE)
    if consensus:
        bullets.append(f"<strong>{len(consensus)} consensus themes</strong> identified (priced in)")

    # Count divergences (### headers under Divergence section)
    divergences = re.findall(r"^### \d+\.\s+(.+)", md_text, re.MULTILINE)
    if divergences:
        bullets.append(f"<strong>{len(divergences)} strategic divergences</strong> surfaced (not priced in)")

    # Count signals
    signals = re.findall(r"^\*\*\d+\.\s+(.+?)\*\*", md_text, re.MULTILINE)
    if signals:
        bullets.append(f"<strong>{len(signals)} cross-company signals</strong> visible only in synthesis")

    # Extract subtitle/tagline
    tagline = re.search(r"^###\s+(.+)", md_text, re.MULTILINE)
    if tagline:
        bullets.append(tagline.group(1).strip())

    return bullets or ["Cross-company sector analysis based on annual report synthesis"]


def generate_brief_pdf(brief_path, output_path=None):
    """Generate a polished PDF from a sector intelligence brief."""
    md_text = Path(brief_path).read_text(encoding="utf-8")
    css = _load_css()

    # Extract sector name and year from title
    title_match = re.search(r"^#\s*Sector Intelligence Brief:\s*(.+?)\s*\|\s*FY(\d{4})", md_text, re.MULTILINE)
    if title_match:
        sector_name = title_match.group(1).strip()
        year = title_match.group(2)
    else:
        sector_name = Path(brief_path).stem.replace("_brief", "").replace("_", " ").title()
        year = "2025"

    # Extract companies
    companies_match = re.search(r"\*\*Companies:\*\*\s*(.+)", md_text)
    companies_str = companies_match.group(1).strip() if companies_match else ""

    cover = _build_cover(
        report_type="Sector Intelligence Brief",
        title=sector_name,
        subtitle=f"Cross-Company Synthesis  |  FY{year}",
        meta_lines=[
            f"<strong>Companies:</strong> {companies_str}",
            f"<strong>Report Date:</strong> {datetime.now().strftime('%B %d, %Y')}",
            "<strong>Source:</strong> Annual Reports — Every claim grounded in company disclosures",
            "<strong>Classification:</strong> Confidential — Subscriber Only",
        ],
    )

    exec_bullets = _parse_brief_exec_summary(md_text)
    exec_html = _build_exec_summary(exec_bullets)

    # Remove the H1 title, subtitle line, and companies line from body
    body_md = md_text
    body_md = re.sub(r"^#\s*Sector Intelligence Brief:.*?\n", "", body_md, count=1)
    body_md = re.sub(r"^###\s+.+?\n", "", body_md, count=1)
    body_md = re.sub(r"^\*\*Companies:\*\*.*?\n", "", body_md, count=1)
    body_md = body_md.strip()

    body_html = _md_to_html_body(body_md)

    disclaimer = _build_disclaimer()

    full_html = _wrap_full_html(css, cover, exec_html, body_html, disclaimer)

    if output_path is None:
        slug = Path(brief_path).stem.replace("_brief", "")
        output_path = OUTPUT_DIR / f"{slug}_brief_v{year}.pdf"

    return _render_pdf(full_html, output_path)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    briefs = list(BRIEFS_DIR.glob("*_brief.md"))
    if not briefs:
        print("No briefs found in", BRIEFS_DIR)
        sys.exit(1)

    print(f"Found {len(briefs)} briefs to convert:\n")
    for brief in briefs:
        print(f"  Processing: {brief.name}")
        pdf_path = generate_brief_pdf(brief)
        print(f"  -> {pdf_path}\n")

    print("Done!")
