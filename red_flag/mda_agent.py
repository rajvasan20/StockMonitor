"""
MD&A Ambient Agent
------------------
Scans annual_reports/ for unprocessed PDFs and extracts MD&A context
into structured markdown files using the mda-context skill + Claude API.

Usage:
    python run.py redflag-mda                        # process all pending PDFs
    python run.py redflag-mda --ticker HDFCBANK      # process one company only
    python run.py redflag-mda --dry-run              # show what would be processed

Requirements:
    pip install anthropic
    Set ANTHROPIC_API_KEY in environment or create a .env file
"""

import os
import sys
import json
import base64
import time
import re
from datetime import datetime
from pathlib import Path

import anthropic

from config import ANNUAL_REPORTS_DIR, BASE_DIR

# ── Paths ────────────────────────────────────────────────────────────────────
REPORTS_DIR   = Path(ANNUAL_REPORTS_DIR)
MANIFEST_FILE = Path(BASE_DIR) / "red_flag" / "_manifest.json"
LOG_FILE      = Path(BASE_DIR) / "red_flag" / "_agent.log"
SKILL_FILE    = Path(os.path.expanduser("~")) / ".claude" / "commands" / "extract-sections.md"

MODEL         = "claude-sonnet-4-6"
DELAY_SECONDS = 3


def log(msg, also_print=True):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    if also_print:
        print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_manifest():
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(manifest):
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def find_pdfs(ticker_filter=None):
    """Return all PDF paths under annual_reports/, optionally filtered by ticker."""
    pdfs = sorted(REPORTS_DIR.rglob("*.pdf"))
    if ticker_filter:
        pdfs = [p for p in pdfs if p.parent.name.upper() == ticker_filter.upper()]
    return pdfs


def parse_filename(pdf_path):
    name = pdf_path.stem
    match = re.match(r"^([A-Z0-9&\-]+)_AnnualReport_FY(\d{4})", name, re.IGNORECASE)
    if match:
        return match.group(1).upper(), match.group(2)
    ticker = pdf_path.parent.name.upper()
    year_match = re.search(r"FY(\d{4})", name, re.IGNORECASE)
    year = year_match.group(1) if year_match else "UNKNOWN"
    return ticker, year


def expected_output_path(pdf_path, ticker, year):
    return pdf_path.parent / f"{ticker}_MDA_FY{year}_context.md"


def load_skill():
    if not SKILL_FILE.exists():
        raise FileNotFoundError(f"Skill file not found: {SKILL_FILE}")
    return SKILL_FILE.read_text(encoding="utf-8")


def extract_mda(client, skill_prompt, pdf_path, ticker, year):
    """Send PDF to Claude with skill instructions. Returns markdown response."""
    pdf_bytes = pdf_path.read_bytes()
    pdf_b64   = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    user_message = (
        f"Process this annual report.\n\n"
        f"Ticker: {ticker}\n"
        f"FY Year: {year}\n"
        f"File: {pdf_path.name}\n\n"
        f"Follow all steps in the skill instructions exactly. "
        f"Return only the completed markdown context file contents \u2014 "
        f"no preamble, no commentary outside the markdown."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=skill_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type":       "base64",
                            "media_type": "application/pdf",
                            "data":       pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_message,
                    },
                ],
            }
        ],
    )

    return response.content[0].text


def process_pdf(client, skill_prompt, pdf_path, manifest, dry_run=False):
    ticker, year = parse_filename(pdf_path)
    manifest_key = pdf_path.name
    output_path  = expected_output_path(pdf_path, ticker, year)

    if manifest.get(manifest_key, {}).get("status") == "done":
        log(f"  SKIP  {pdf_path.name} \u2014 already in manifest")
        return "skipped"

    if output_path.exists():
        log(f"  SKIP  {pdf_path.name} \u2014 output file already exists")
        manifest[manifest_key] = {
            "status": "done",
            "output": output_path.name,
            "note":   "output existed, added to manifest retroactively",
            "processed_at": datetime.now().strftime("%Y-%m-%d"),
        }
        save_manifest(manifest)
        return "skipped"

    if dry_run:
        log(f"  DRY   {pdf_path.name} -> {output_path.name}")
        return "dry-run"

    log(f"  PROC  {pdf_path.name} ({ticker} FY{year})")

    try:
        markdown = extract_mda(client, skill_prompt, pdf_path, ticker, year)
        output_path.write_text(markdown, encoding="utf-8")

        blocks_present = re.findall(r"## Block \d+\w*", markdown)
        blocks_absent  = re.findall(r"Not present in this report", markdown)
        sector_match   = re.search(
            r"Sector Type\s*\|\s*(BANKING|HEALTHCARE|MINING|OTHER)", markdown
        )
        sector = sector_match.group(1) if sector_match else "UNKNOWN"

        manifest[manifest_key] = {
            "status":        "done",
            "output":         output_path.name,
            "ticker":         ticker,
            "year":           year,
            "sector":         sector,
            "blocks_present": len(blocks_present),
            "blocks_absent":  len(blocks_absent),
            "processed_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_manifest(manifest)
        log(f"  DONE  {output_path.name} | sector={sector} | blocks={len(blocks_present)}")
        return "done"

    except Exception as e:
        error_msg = str(e)
        log(f"  FAIL  {pdf_path.name} \u2014 {error_msg}")
        manifest[manifest_key] = {
            "status":       "failed",
            "error":        error_msg,
            "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_manifest(manifest)
        return "failed"


def run(ticker=None, dry_run=False, retry_failed=False):
    """Main entry point for MD&A extraction."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key and not dry_run:
        env_file = Path(BASE_DIR) / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key and not dry_run:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        print("  Set environment variable ANTHROPIC_API_KEY=sk-...")
        return

    client       = anthropic.Anthropic(api_key=api_key) if not dry_run else None
    skill_prompt = load_skill()
    manifest     = load_manifest()

    if retry_failed:
        cleared = [k for k, v in manifest.items() if v.get("status") == "failed"]
        for k in cleared:
            del manifest[k]
        save_manifest(manifest)
        log(f"Cleared {len(cleared)} failed entries for retry.")

    pdfs = find_pdfs(ticker_filter=ticker)
    log(f"{'='*60}")
    log(f"MD&A Agent started | PDFs found: {len(pdfs)} | dry-run: {dry_run}")
    log(f"{'='*60}")

    counts = {"done": 0, "skipped": 0, "failed": 0, "dry-run": 0}

    for i, pdf_path in enumerate(pdfs, 1):
        log(f"[{i}/{len(pdfs)}]", also_print=True)
        status = process_pdf(client, skill_prompt, pdf_path, manifest,
                             dry_run=dry_run)
        counts[status] += 1

        if status == "done" and i < len(pdfs):
            time.sleep(DELAY_SECONDS)

    log(f"{'='*60}")
    log(f"Run complete | done={counts['done']} skipped={counts['skipped']} "
        f"failed={counts['failed']} dry-run={counts['dry-run']}")
    log(f"{'='*60}")
