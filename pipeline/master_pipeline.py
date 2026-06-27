"""
Master Pipeline — Full depth-first extraction per company
==========================================================
Runs the complete analysis pipeline for each company before moving to the next:

    Step 1: /extract-sections  → MDA + Notes markdown (per year)
    Step 2: /extract-notes-json → Lossless Notes JSON (per year)
    Step 3: /extract-kpis      → KPI database JSON (per company)
    Step 4: /extract-forensics  → Forensic database JSON (per company)

Skips steps where output already exists. Tracks progress in pipeline_state.json.

Usage:
    # Run full pipeline for all companies (Nifty 100 first)
    python pipeline/master_pipeline.py

    # Run for specific company
    python pipeline/master_pipeline.py --ticker RELIANCE

    # Dry run
    python pipeline/master_pipeline.py --dry-run

    # Status check
    python pipeline/master_pipeline.py --status

    # Skip to specific step (e.g., already have MDA, start from notes)
    python pipeline/master_pipeline.py --start-step 2

    # Run specific batch slice for parallel terminals
    python pipeline/master_pipeline.py --batch 1/3

    # Limit companies
    python pipeline/master_pipeline.py --limit 5
"""

import json
import subprocess
import sys
import io
import re
import time
import argparse
from pathlib import Path
from datetime import datetime
from glob import glob

# Fix Windows encoding + force line buffering for background/piped runs
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

PROJECT_ROOT = Path(r"C:/Users/VinothRajapandian/Personal Claude/Stock Monitor")
AR_DIR = PROJECT_ROOT / "data" / "annual_reports"
KPI_DIR = PROJECT_ROOT / "data" / "kpi_database"
FORENSIC_DIR = PROJECT_ROOT / "data" / "notes_database"
STATE_PATH = PROJECT_ROOT / "pipeline" / "pipeline_state.json"
LOG_DIR = PROJECT_ROOT / "pipeline" / "logs"

CLAUDE_BIN = r"C:\Users\VinothRajapandian\AppData\Roaming\npm\claude.cmd"

# Nifty 100 companies (prioritized) — large-caps that investors care about most
NIFTY_100 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "ITC",
    "SBIN", "LT", "AXISBANK", "KOTAKBANK", "M&M", "MARUTI", "TITAN",
    "SUNPHARMA", "BAJFINANCE", "HCLTECH", "WIPRO", "TATAMOTORS", "ADANIENT",
    "ADANIPORTS", "NTPC", "POWERGRID", "ONGC", "BPCL", "COALINDIA",
    "BAJAJ-AUTO", "BAJAJFINSV", "NESTLEIND", "ULTRACEMCO", "GRASIM",
    "JSWSTEEL", "TATASTEEL", "HINDUNILVR", "ASIANPAINT", "BRITANNIA",
    "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP", "EICHERMOT", "HEROMOTOCO",
    "INDUSINDBK", "HDFCLIFE", "SBILIFE", "ICICIPRULI", "SHREECEM",
    "TATACONSUM", "PIDILITIND", "ABB", "CUMMINSIND", "CDSL", "TECHM",
    "ZYDUSLIFE", "INDUSTOWER", "PERSISTENT", "KPITTECH", "COFORGE",
    "LALPATHLAB", "TATAELXSI", "MCX", "IEX", "CRISIL", "BERGEPAINT",
    "HINDPETRO",
]

# Rest of universe (smaller companies, processed after Nifty 100)
OTHERS = [
    "AGIIL", "AHCL", "ALKYLAMINE", "ALLDIGI", "BLS", "CAMS", "CONTROLPR",
    "ECLERX", "FORTIS", "GPIL", "GRAUWEIL", "GRINDWELL", "GRWRHITECH",
    "INDIAMART", "INOXINDIA", "JBCHEPHARM", "JLHL", "JYOTHYLAB", "KANSAINER",
    "KFINTECH", "KIRLOSENG", "LTM", "MAXHEALTH", "MEDANTA", "NATCOPHARM",
    "NATIONALUM", "NCC", "NEWGEN", "NH", "PIIND", "RAINBOW", "RAJESHEXPO",
    "SOLARINDS", "SUPREMEIND", "TATATECH", "TRITURBINE", "VIJAYA",
    "WAAREERTL",
]


def get_company_order():
    """Nifty 100 first, then others. Only companies with PDFs."""
    ordered = []
    for ticker in NIFTY_100 + OTHERS:
        ticker_dir = AR_DIR / ticker
        if ticker_dir.exists() and list(ticker_dir.glob(f"{ticker}_AnnualReport_FY*.pdf")):
            ordered.append(ticker)
    return ordered


def get_fy_years(ticker):
    """Get available FY years for a company, sorted ascending."""
    ticker_dir = AR_DIR / ticker
    years = []
    for pdf in ticker_dir.glob(f"{ticker}_AnnualReport_FY*.pdf"):
        fy = pdf.stem.split("_FY")[-1]
        years.append(f"FY{fy}")
    return sorted(years)


def check_company_state(ticker):
    """Check what's already done for a company."""
    ticker_dir = AR_DIR / ticker
    years = get_fy_years(ticker)

    state = {
        "ticker": ticker,
        "years": years,
        "mda": {},       # year → bool
        "notes_json": {},  # year → bool
        "kpi": False,
        "forensic": False,
    }

    for fy in years:
        # MDA: check for {TICKER}_MDA_FY{YEAR}_context.md or {TICKER}_MDA_Context_FY{YEAR}.md
        mda_patterns = [
            ticker_dir / f"{ticker}_MDA_{fy}_context.md",
            ticker_dir / f"{ticker}_MDA_Context_{fy}.md",
        ]
        state["mda"][fy] = any(p.exists() for p in mda_patterns)

        # Notes JSON
        state["notes_json"][fy] = (ticker_dir / f"{ticker}_Notes_{fy}.json").exists()

    # KPI database
    state["kpi"] = (KPI_DIR / f"{ticker}.json").exists()

    # Forensic database
    state["forensic"] = (FORENSIC_DIR / f"{ticker}.json").exists()

    return state


# Error categories — callers use these to decide whether to retry/wait/abort
ERR_RATE_LIMIT = "RATE_LIMIT"
ERR_NETWORK = "NETWORK"
ERR_AUTH = "AUTH"
ERR_TIMEOUT = "TIMEOUT"
ERR_UNKNOWN = "UNKNOWN"

MAX_RETRIES = 3
NETWORK_RETRY_WAIT = 30  # seconds


def _classify_error(stdout, stderr):
    """Classify a failed claude CLI run into an error category."""
    combined = (stdout or "") + (stderr or "")
    if "hit your limit" in combined or "rate limit" in combined.lower():
        # Extract reset time if available (e.g., "resets 2:50pm (Asia/Calcutta)")
        match = re.search(r"resets?\s+(\d{1,2}:\d{2}(?:am|pm))", combined, re.IGNORECASE)
        reset_time = match.group(1) if match else None
        return ERR_RATE_LIMIT, reset_time
    if "ENOTFOUND" in combined or "Unable to connect" in combined:
        return ERR_NETWORK, None
    if "authentication_error" in combined or "Invalid authentication" in combined:
        return ERR_AUTH, None
    return ERR_UNKNOWN, None


def _parse_reset_time(reset_str):
    """Parse '2:50pm' into seconds to wait from now. Returns wait seconds."""
    if not reset_str:
        return 300  # default 5 min wait if we can't parse
    try:
        now = datetime.now()
        # Parse time like "2:50pm" or "1:30pm"
        reset_dt = datetime.strptime(reset_str, "%I:%M%p").replace(
            year=now.year, month=now.month, day=now.day
        )
        # If reset time is in the past, it might be tomorrow or just passed
        diff = (reset_dt - now).total_seconds()
        if diff < 0:
            # Already past — wait 2 minutes as buffer
            return 120
        # Add 60s buffer so we don't hit the edge
        return diff + 60
    except (ValueError, TypeError):
        return 300


def run_claude(prompt, ticker, step_name, timeout=900):
    """Run a claude CLI command with retry logic.

    Returns (success: bool, error: str|None, error_category: str|None).
    - On rate limit: waits for reset, then retries (up to MAX_RETRIES).
    - On network error: retries with backoff (up to MAX_RETRIES).
    - On auth error: fails immediately (not transient).
    """

    print(f"    Running: {step_name}")
    print(f"    Prompt: {prompt}")

    cmd = [
        CLAUDE_BIN,
        "-p", prompt,
        "--allowedTools", "Read,Write,Bash,Glob,Grep",
        "--max-turns", "80",
    ]

    LOG_DIR.mkdir(exist_ok=True)

    for attempt in range(1, MAX_RETRIES + 1):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = LOG_DIR / f"{ticker}_{step_name}_{timestamp}.log"
        start = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(PROJECT_ROOT),
                encoding="utf-8",
                errors="replace",
            )

            elapsed = time.time() - start

            log_file.write_text(
                f"COMMAND: {' '.join(cmd)}\n"
                f"ATTEMPT: {attempt}/{MAX_RETRIES}\n"
                f"RETURN CODE: {result.returncode}\n"
                f"ELAPSED: {elapsed:.0f}s\n"
                f"STDOUT:\n{result.stdout[:5000]}\n"
                f"STDERR:\n{result.stderr[:2000]}\n",
                encoding="utf-8",
            )

            if result.returncode == 0:
                print(f"    ✓ Done ({elapsed:.0f}s)")
                return True, None, None

            # Classify the failure
            category, extra = _classify_error(result.stdout, result.stderr)

            if category == ERR_RATE_LIMIT:
                wait_secs = _parse_reset_time(extra)
                reset_info = extra or "unknown"
                print(f"    ⏳ Rate limited (resets {reset_info}). "
                      f"Waiting {wait_secs/60:.0f} min before retry {attempt}/{MAX_RETRIES}...")
                time.sleep(wait_secs)
                continue

            if category == ERR_NETWORK:
                wait = NETWORK_RETRY_WAIT * attempt
                print(f"    🔌 Network error. Retrying in {wait}s "
                      f"(attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue

            if category == ERR_AUTH:
                print(f"    ✗ Auth error — not retryable")
                return False, "Authentication error", ERR_AUTH

            # Unknown error — don't retry
            error = f"Exit code {result.returncode}"
            print(f"    ✗ FAILED: {error} ({elapsed:.0f}s)")
            return False, error, ERR_UNKNOWN

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            print(f"    ✗ TIMEOUT after {elapsed:.0f}s")
            log_file.write_text(
                f"COMMAND: {' '.join(cmd)}\n"
                f"ATTEMPT: {attempt}/{MAX_RETRIES}\n"
                f"TIMEOUT after {timeout}s\n",
                encoding="utf-8",
            )
            return False, f"Timeout after {timeout}s", ERR_TIMEOUT

        except Exception as e:
            print(f"    ✗ ERROR: {e}")
            log_file.write_text(f"EXCEPTION: {e}\n", encoding="utf-8")
            return False, str(e), ERR_UNKNOWN

    # Exhausted retries (only rate limit / network reach here)
    print(f"    ✗ Exhausted {MAX_RETRIES} retries")
    return False, f"Exhausted {MAX_RETRIES} retries", ERR_RATE_LIMIT


def run_company_pipeline(ticker, start_step=1, dry_run=False):
    """Run the full pipeline for one company. Returns summary dict.

    Checks output files to determine completion (not state file),
    so rate-limited runs that produced nothing are automatically retried.
    """

    state = check_company_state(ticker)
    years = state["years"]
    results = {"ticker": ticker, "steps": {}, "errors": [], "aborted": False}

    print(f"\n{'='*60}")
    print(f"  COMPANY: {ticker}")
    print(f"  Years: {', '.join(years)}")
    print(f"{'='*60}")

    # ── Step 1: Extract MDA (per year) ──
    if start_step <= 1:
        missing_mda = [fy for fy in years if not state["mda"][fy]]
        if missing_mda:
            print(f"\n  Step 1: Extract MDA — {len(missing_mda)} years needed")
            step_ok = True
            for fy in missing_mda:
                year_num = fy.replace("FY", "")
                if dry_run:
                    print(f"    [DRY RUN] /extract-sections {ticker} {year_num}")
                    continue
                ok, err, cat = run_claude(
                    f"/extract-sections {ticker} {year_num}",
                    ticker, f"mda_{fy}"
                )
                if not ok:
                    results["errors"].append(f"MDA {fy}: {err}")
                    step_ok = False
                    if cat == ERR_AUTH:
                        results["aborted"] = True
                        print(f"  ⛔ Auth error — aborting pipeline")
                        return results
            results["steps"]["mda"] = "done" if (not dry_run and step_ok) else \
                                      "partial" if not step_ok else "dry_run"
        else:
            print(f"\n  Step 1: Extract MDA — already complete ({len(years)} years)")
            results["steps"]["mda"] = "skipped"

    # ── Step 2: Extract Notes JSON (per year) ──
    if start_step <= 2:
        # Re-check state in case Step 1 just produced new files
        state = check_company_state(ticker)
        missing_notes = [fy for fy in years if not state["notes_json"][fy]]
        if missing_notes:
            print(f"\n  Step 2: Extract Notes JSON — {len(missing_notes)} years needed")
            step_ok = True
            for fy in missing_notes:
                if dry_run:
                    print(f"    [DRY RUN] /extract-notes-json {ticker} {fy}")
                    continue
                ok, err, cat = run_claude(
                    f"/extract-notes-json {ticker} {fy}",
                    ticker, f"notes_{fy}"
                )
                if not ok:
                    results["errors"].append(f"Notes JSON {fy}: {err}")
                    step_ok = False
                    if cat == ERR_AUTH:
                        results["aborted"] = True
                        return results
            results["steps"]["notes_json"] = "done" if (not dry_run and step_ok) else \
                                              "partial" if not step_ok else "dry_run"
        else:
            print(f"\n  Step 2: Extract Notes JSON — already complete ({len(years)} years)")
            results["steps"]["notes_json"] = "skipped"

    # ── Step 3: Extract KPIs (per company) ──
    if start_step <= 3:
        refreshed = check_company_state(ticker)
        if not refreshed["kpi"]:
            print(f"\n  Step 3: Extract KPIs")
            mda_count = sum(1 for v in refreshed["mda"].values() if v)
            if mda_count == 0:
                print(f"    SKIPPED: No MDA files available (dependency not met)")
                results["steps"]["kpi"] = "skipped_no_mda"
            elif dry_run:
                print(f"    [DRY RUN] /extract-kpis {ticker}")
                results["steps"]["kpi"] = "dry_run"
            else:
                ok, err, cat = run_claude(
                    f"/extract-kpis {ticker}",
                    ticker, "kpis"
                )
                results["steps"]["kpi"] = "done" if ok else "failed"
                if not ok:
                    results["errors"].append(f"KPIs: {err}")
                    if cat == ERR_AUTH:
                        results["aborted"] = True
                        return results
        else:
            print(f"\n  Step 3: Extract KPIs — already complete")
            results["steps"]["kpi"] = "skipped"

    # ── Step 4: Extract Forensics (per company) ──
    if start_step <= 4:
        refreshed = check_company_state(ticker)
        if not refreshed["forensic"]:
            print(f"\n  Step 4: Extract Forensics")
            notes_count = sum(1 for v in refreshed["notes_json"].values() if v)
            if notes_count == 0:
                print(f"    SKIPPED: No Notes JSON files available (dependency not met)")
                results["steps"]["forensic"] = "skipped_no_notes"
            elif dry_run:
                print(f"    [DRY RUN] /extract-forensics {ticker}")
                results["steps"]["forensic"] = "dry_run"
            else:
                ok, err, cat = run_claude(
                    f"/extract-forensics {ticker}",
                    ticker, "forensics"
                )
                results["steps"]["forensic"] = "done" if ok else "failed"
                if not ok:
                    results["errors"].append(f"Forensics: {err}")
                    if cat == ERR_AUTH:
                        results["aborted"] = True
                        return results
        else:
            print(f"\n  Step 4: Extract Forensics — already complete")
            results["steps"]["forensic"] = "skipped"

    # ── Summary ──
    print(f"\n  {'─'*40}")
    print(f"  {ticker} COMPLETE")
    for step, status in results["steps"].items():
        marker = "✓" if status in ("done", "skipped") else status.upper()
        print(f"    {step:15s} {marker}")
    if results["errors"]:
        print(f"  Errors: {len(results['errors'])}")
        for e in results["errors"]:
            print(f"    - {e}")

    return results


def load_state():
    """Load pipeline state (tracks which companies are fully done)."""
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"companies": {}, "started": datetime.now().isoformat()}


def save_state(state):
    state["last_updated"] = datetime.now().isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def print_status():
    """Print full pipeline status."""
    companies = get_company_order()

    print(f"\n{'='*70}")
    print(f"  MASTER PIPELINE STATUS")
    print(f"{'='*70}")

    nifty_done = 0
    nifty_total = 0
    other_done = 0
    other_total = 0

    print(f"\n  {'TICKER':20s} {'YRS':>4s} {'MDA':>5s} {'JSON':>5s} {'KPI':>4s} {'FOR':>4s} {'STATUS':>10s}")
    print(f"  {'─'*56}")

    for ticker in companies:
        state = check_company_state(ticker)
        years = state["years"]
        n_years = len(years)
        n_mda = sum(1 for v in state["mda"].values() if v)
        n_notes = sum(1 for v in state["notes_json"].values() if v)
        kpi = "Y" if state["kpi"] else "-"
        forensic = "Y" if state["forensic"] else "-"

        # Full pipeline = all MDA + all Notes JSON + KPI + Forensic
        is_complete = (n_mda == n_years and n_notes == n_years
                       and state["kpi"] and state["forensic"])
        status = "DONE" if is_complete else "partial" if (n_mda + n_notes > 0) else "pending"

        is_nifty = ticker in NIFTY_100
        if is_nifty:
            nifty_total += 1
            if is_complete:
                nifty_done += 1
        else:
            other_total += 1
            if is_complete:
                other_done += 1

        prefix = "N" if is_nifty else " "
        mda_str = f"{n_mda}/{n_years}"
        notes_str = f"{n_notes}/{n_years}"
        print(f"  {prefix} {ticker:18s} {n_years:4d} {mda_str:>5s} {notes_str:>5s} {kpi:>4s} {forensic:>4s} {status:>10s}")

    print(f"\n  {'─'*56}")
    print(f"  Nifty 100: {nifty_done}/{nifty_total} complete")
    print(f"  Others:    {other_done}/{other_total} complete")
    print(f"  Total:     {nifty_done + other_done}/{nifty_total + other_total} complete")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Master depth-first pipeline")
    parser.add_argument("--ticker", help="Run for specific company only")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    parser.add_argument("--start-step", type=int, default=1,
                        help="Start from step N (1=MDA, 2=Notes, 3=KPIs, 4=Forensics)")
    parser.add_argument("--batch", help="Batch slice: 1/3, 2/3, etc.")
    parser.add_argument("--limit", type=int, help="Max companies to process")
    parser.add_argument("--nifty-only", action="store_true", help="Only Nifty 100 companies")
    parser.add_argument("--reset-state", action="store_true",
                        help="Clear pipeline_state.json (re-derive progress from output files)")
    args = parser.parse_args()

    if args.reset_state:
        if STATE_PATH.exists():
            STATE_PATH.unlink()
            print("Pipeline state reset. Progress will be re-derived from output files.")
        else:
            print("No state file to reset.")
        if not args.status:
            return

    if args.status:
        print_status()
        return

    # Determine company list
    if args.ticker:
        companies = [args.ticker]
    else:
        companies = get_company_order()
        if args.nifty_only:
            companies = [c for c in companies if c in NIFTY_100]

    # Batch slicing
    if args.batch:
        batch_num, total = map(int, args.batch.split("/"))
        companies = [c for i, c in enumerate(companies) if (i % total) == (batch_num - 1)]
        print(f"Batch {batch_num}/{total}: {len(companies)} companies")

    # Skip fully complete companies
    pending = []
    for ticker in companies:
        state = check_company_state(ticker)
        years = state["years"]
        n_years = len(years)
        n_mda = sum(1 for v in state["mda"].values() if v)
        n_notes = sum(1 for v in state["notes_json"].values() if v)
        is_complete = (n_mda == n_years and n_notes == n_years
                       and state["kpi"] and state["forensic"])
        if not is_complete:
            pending.append(ticker)

    if args.limit:
        pending = pending[:args.limit]

    if not pending:
        print("All companies in scope are fully complete.")
        return

    print(f"\nMaster Pipeline: {len(pending)} companies to process")
    if args.dry_run:
        print("(DRY RUN — no actual extractions)")

    # Load state
    pipeline_state = load_state()
    start_time = time.time()
    completed = 0

    for i, ticker in enumerate(pending):
        print(f"\n[Company {i+1}/{len(pending)}]")

        results = run_company_pipeline(ticker, args.start_step, args.dry_run)

        # Save state — only record what actually succeeded
        pipeline_state["companies"][ticker] = {
            "steps": results["steps"],
            "errors": results["errors"],
            "processed_at": datetime.now().isoformat(),
        }
        save_state(pipeline_state)

        if results.get("aborted"):
            print(f"\n  ⛔ Pipeline aborted at {ticker} due to auth error.")
            print(f"  Fix credentials and re-run to continue.")
            break

        completed += 1
        elapsed = time.time() - start_time
        if completed > 1:
            avg = elapsed / completed
            remaining = avg * (len(pending) - i - 1)
            print(f"\n  Overall: {completed}/{len(pending)} companies, "
                  f"~{remaining/3600:.1f} hours remaining")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  PIPELINE {'ABORTED' if results.get('aborted') else 'COMPLETE'}")
    print(f"  Companies processed: {completed}/{len(pending)}")
    print(f"  Total time: {elapsed/3600:.1f} hours")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
