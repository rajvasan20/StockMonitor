"""
Batch Notes Extraction Pipeline
================================
Runs /extract-notes-json via Claude Code CLI for each pending job in manifest.json.

Usage:
    # Extract all pending (sequential)
    python pipeline/batch_extract.py

    # Extract specific company
    python pipeline/batch_extract.py --ticker BAJAJ-AUTO

    # Extract specific company + year
    python pipeline/batch_extract.py --ticker BAJAJ-AUTO --fy FY2025

    # Dry run (show what would be extracted)
    python pipeline/batch_extract.py --dry-run

    # Retry failed jobs
    python pipeline/batch_extract.py --retry-failed

    # Limit number of extractions (useful for testing)
    python pipeline/batch_extract.py --limit 5

    # Run a specific batch slice (for parallel terminals)
    python pipeline/batch_extract.py --batch 1/3    # terminal 1 of 3
    python pipeline/batch_extract.py --batch 2/3    # terminal 2 of 3
    python pipeline/batch_extract.py --batch 3/3    # terminal 3 of 3

For parallel execution with multiple licenses:
    # Terminal 1 (license 1): odd-indexed companies
    python pipeline/batch_extract.py --batch 1/5
    # Terminal 2 (license 2):
    python pipeline/batch_extract.py --batch 2/5
    # ... up to 5 or 10 terminals
"""

import json
import subprocess
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(r"C:/Users/VinothRajapandian/Personal Claude/Stock Monitor")
MANIFEST_PATH = PROJECT_ROOT / "pipeline" / "manifest.json"
LOG_DIR = PROJECT_ROOT / "pipeline" / "logs"


def load_manifest():
    if not MANIFEST_PATH.exists():
        print("ERROR: manifest.json not found. Run build_manifest.py first.")
        sys.exit(1)
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_manifest(manifest):
    # Recompute counts
    manifest["pending"] = sum(1 for j in manifest["jobs"] if j["status"] == "pending")
    manifest["done"] = sum(1 for j in manifest["jobs"] if j["status"] == "done")
    manifest["failed"] = sum(1 for j in manifest["jobs"] if j["status"] == "failed")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_extraction(ticker, fy):
    """Run claude CLI to extract notes for one company-year."""

    prompt = f"/extract-notes-json {ticker} {fy}"

    print(f"\n{'='*60}")
    print(f"  EXTRACTING: {ticker} {fy}")
    print(f"  Time: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    # Build claude command — use .cmd extension on Windows
    claude_bin = r"C:\Users\VinothRajapandian\AppData\Roaming\npm\claude.cmd"
    cmd = [
        claude_bin,
        "-p", prompt,
        "--allowedTools", "Read,Write,Bash,Glob,Grep",
        "--max-turns", "80",
    ]

    # Create log file
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{ticker}_{fy}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2700,  # 45 min timeout per extraction
            cwd=str(PROJECT_ROOT),
            encoding="utf-8",
            errors="replace",
        )

        # Write log
        log_file.write_text(
            f"COMMAND: {' '.join(cmd)}\n"
            f"RETURN CODE: {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}\n",
            encoding="utf-8",
        )

        # Check if JSON was actually created
        json_path = PROJECT_ROOT / "data" / "annual_reports" / ticker / f"{ticker}_Notes_{fy}.json"
        if json_path.exists():
            size = json_path.stat().st_size
            print(f"  SUCCESS: {json_path.name} ({size:,} bytes)")
            return "done", None
        else:
            print(f"  FAILED: JSON not created (exit code {result.returncode})")
            return "failed", f"JSON not created. Exit code: {result.returncode}"

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT: Exceeded 45 minutes")
        log_file.write_text(f"TIMEOUT after 2700 seconds\n", encoding="utf-8")
        return "failed", "Timeout after 45 minutes"

    except Exception as e:
        print(f"  ERROR: {e}")
        log_file.write_text(f"EXCEPTION: {e}\n", encoding="utf-8")
        return "failed", str(e)


def get_pending_jobs(manifest, args):
    """Filter jobs based on CLI args."""

    jobs = manifest["jobs"]

    # Filter by status
    if args.retry_failed:
        jobs = [j for j in jobs if j["status"] == "failed"]
    else:
        jobs = [j for j in jobs if j["status"] == "pending"]

    # Filter by ticker
    if args.ticker:
        jobs = [j for j in jobs if j["ticker"] == args.ticker]

    # Filter by FY
    if args.fy:
        jobs = [j for j in jobs if j["fy"] == args.fy]

    # Batch slicing for parallel terminals
    if args.batch:
        batch_num, total_batches = map(int, args.batch.split("/"))
        # Distribute by ticker to keep company years together
        tickers = sorted(set(j["ticker"] for j in jobs))
        my_tickers = [t for i, t in enumerate(tickers) if (i % total_batches) == (batch_num - 1)]
        jobs = [j for j in jobs if j["ticker"] in my_tickers]
        print(f"Batch {batch_num}/{total_batches}: {len(my_tickers)} companies assigned")

    # Apply limit
    if args.limit:
        jobs = jobs[:args.limit]

    return jobs


def print_status(manifest):
    """Print current extraction status."""
    total = manifest["total_jobs"]
    done = manifest["done"]
    failed = manifest["failed"]
    pending = manifest["pending"]

    print(f"\n{'='*60}")
    print(f"  EXTRACTION STATUS")
    print(f"{'='*60}")
    print(f"  Total:   {total}")
    print(f"  Done:    {done} ({done/total*100:.1f}%)")
    print(f"  Failed:  {failed}")
    print(f"  Pending: {pending}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Batch Notes JSON extraction")
    parser.add_argument("--ticker", help="Extract specific company only")
    parser.add_argument("--fy", help="Extract specific year only (e.g. FY2025)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be extracted")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed jobs")
    parser.add_argument("--limit", type=int, help="Max extractions to run")
    parser.add_argument("--batch", help="Batch slice for parallel: 1/3, 2/3, etc.")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    args = parser.parse_args()

    manifest = load_manifest()

    if args.status:
        print_status(manifest)

        # Show per-company status
        tickers = sorted(set(j["ticker"] for j in manifest["jobs"]))
        for t in tickers:
            t_jobs = [j for j in manifest["jobs"] if j["ticker"] == t]
            done = sum(1 for j in t_jobs if j["status"] == "done")
            failed = sum(1 for j in t_jobs if j["status"] == "failed")
            total = len(t_jobs)
            status = "DONE" if done == total else f"{done}/{total}"
            if failed:
                status += f" ({failed} failed)"
            print(f"  {t:20s} {status}")
        return

    pending = get_pending_jobs(manifest, args)

    if not pending:
        print("No pending jobs matching filters.")
        return

    if args.dry_run:
        print(f"\nWould extract {len(pending)} jobs:")
        for j in pending:
            print(f"  {j['ticker']} {j['fy']}")
        return

    print(f"\nStarting extraction: {len(pending)} jobs")
    print(f"Estimated time: {len(pending) * 15}-{len(pending) * 25} minutes")

    start_time = time.time()
    completed = 0
    failed = 0

    for i, job in enumerate(pending):
        ticker = job["ticker"]
        fy = job["fy"]

        print(f"\n[{i+1}/{len(pending)}] ", end="")

        # Update manifest: mark as in-progress
        for j in manifest["jobs"]:
            if j["ticker"] == ticker and j["fy"] == fy:
                j["started_at"] = datetime.now().isoformat()
                j["attempt"] += 1
                break
        save_manifest(manifest)

        # Run extraction
        status, error = run_extraction(ticker, fy)

        # Update manifest with result
        for j in manifest["jobs"]:
            if j["ticker"] == ticker and j["fy"] == fy:
                j["status"] = status
                j["error"] = error
                if status == "done":
                    j["completed_at"] = datetime.now().isoformat()
                break
        save_manifest(manifest)

        if status == "done":
            completed += 1
        else:
            failed += 1

        # Progress update
        elapsed = time.time() - start_time
        avg_time = elapsed / (i + 1)
        remaining = avg_time * (len(pending) - i - 1)
        print(f"  Progress: {completed} done, {failed} failed, "
              f"~{remaining/60:.0f} min remaining")

    # Final summary
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE")
    print(f"  Completed: {completed}")
    print(f"  Failed: {failed}")
    print(f"  Time: {elapsed/60:.1f} minutes")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
