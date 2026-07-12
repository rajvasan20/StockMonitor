"""
Ambient /analyze Runner
-----------------------
Fire-and-forget script that runs /analyze for each quality ticker via Claude Code CLI.
Handles usage limits by waiting and resuming. Tracks state for crash recovery.

Usage:
    python scripts/ambient_analyzer.py                # run all pending
    python scripts/ambient_analyzer.py --dry-run      # show what would run
    python scripts/ambient_analyzer.py --reset        # clear state, start fresh
    python scripts/ambient_analyzer.py --status       # show progress

How it works:
    1. Reads quality tickers from _quality_data.json
    2. Skips tickers that already have _integrated.md output
    3. For each pending ticker, invokes: claude -p "/analyze TICKER" --dangerously-skip-permissions
    4. On usage limit (exit code or output detection), waits and retries
    5. State file tracks progress — restart the script anytime to resume
"""

import os
import sys
import json
import subprocess
import time
import argparse
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
QUALITY_DATA = BASE_DIR / "output" / "quality_reports" / "_quality_data.json"
INTEGRATED_DIR = BASE_DIR / "output" / "quality_reports"
STATE_FILE = BASE_DIR / "scripts" / "_ambient_state.json"
LOG_FILE = BASE_DIR / "scripts" / "_ambient_analyzer.log"

# ── Config ───────────────────────────────────────────────────────────────────
USAGE_LIMIT_FALLBACK_WAIT = 300  # 5 min fallback if reset time can't be parsed
USAGE_LIMIT_MAX_WAIT = 3600     # 1 hour max fallback wait
BETWEEN_TICKERS_DELAY = 10      # seconds between tickers (breathing room)
MAX_RETRIES_PER_TICKER = 3      # max retries for a single ticker before moving on

# Strings that indicate usage limit in Claude CLI output
USAGE_LIMIT_SIGNALS = [
    "you've hit your",
    "usage limit",
    "rate limit",
    "too many requests",
    "try again later",
    "overloaded",
    "resets in",
]


def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def clear_state():
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        log("State file cleared.")


def get_quality_tickers():
    with open(QUALITY_DATA, encoding="utf-8") as f:
        data = json.load(f)
    return [d["ticker"] for d in data]


def is_completed(ticker):
    """Check if /analyze has already produced the integrated report."""
    return (INTEGRATED_DIR / f"{ticker}_integrated.md").exists()


def get_pending_tickers():
    """Return tickers that don't have an integrated report yet."""
    all_tickers = get_quality_tickers()
    return [t for t in all_tickers if not is_completed(t)]


def detect_usage_limit(output_text):
    """Check if Claude CLI output indicates a usage limit."""
    lower = output_text.lower()
    return any(signal in lower for signal in USAGE_LIMIT_SIGNALS)


def parse_reset_duration(output_text):
    """Parse the reset time from Claude CLI output.

    The CLI prints messages like:
        "You've hit your fast limit · resets in 1h 30m"
        "You've hit your limit · resets in 45m"
        "resets in 2h"

    Returns seconds to wait, or None if not parseable.
    """
    import re
    # Look for "resets in Xh Ym" or "resets in Xm" or "resets in Xh"
    match = re.search(r'resets\s+in\s+((?:\d+[dhm]\s*)+)', output_text, re.IGNORECASE)
    if not match:
        return None

    duration_str = match.group(1).strip()
    total_seconds = 0

    days = re.search(r'(\d+)d', duration_str)
    hours = re.search(r'(\d+)h', duration_str)
    minutes = re.search(r'(\d+)m', duration_str)

    if days:
        total_seconds += int(days.group(1)) * 86400
    if hours:
        total_seconds += int(hours.group(1)) * 3600
    if minutes:
        total_seconds += int(minutes.group(1)) * 60

    # Add 60s buffer to avoid hitting the limit again immediately
    return total_seconds + 60 if total_seconds > 0 else None


def run_analyze(ticker):
    """Invoke claude CLI to run /analyze for a single ticker.

    Returns:
        (success: bool, usage_limit_hit: bool, output: str)
    """
    prompt = f"/analyze {ticker}"

    cmd = [
        "claude",
        "-p", prompt,
        "--dangerously-skip-permissions",
        "--model", "opus",
        "--verbose",
    ]

    log(f"  CMD   {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout per ticker (these are long)
            cwd=str(BASE_DIR),
        )

        output = (result.stdout or "") + (result.stderr or "")

        # Check for usage limit
        if detect_usage_limit(output):
            log(f"  LIMIT {ticker} — usage limit detected in output")
            return False, True, output

        # Check exit code
        if result.returncode != 0:
            # Non-zero exit could be usage limit or other error
            if detect_usage_limit(output):
                return False, True, output
            log(f"  FAIL  {ticker} — exit code {result.returncode}")
            log(f"  STDERR: {(result.stderr or '')[:500]}")
            return False, False, output

        # Verify the integrated report was actually created
        if is_completed(ticker):
            log(f"  DONE  {ticker} — integrated report created")
            return True, False, output
        else:
            log(f"  WARN  {ticker} — claude exited 0 but no integrated report found")
            return False, False, output

    except subprocess.TimeoutExpired:
        log(f"  TIMEOUT {ticker} — exceeded 2 hour limit")
        return False, False, "timeout"
    except FileNotFoundError:
        log("  ERROR claude CLI not found — is it installed and on PATH?")
        sys.exit(1)


def run_ambient(dry_run=False):
    """Main ambient loop — processes all pending tickers with retry logic."""

    pending = get_pending_tickers()
    total_quality = len(get_quality_tickers())

    log(f"{'=' * 60}")
    log(f"AMBIENT ANALYZER")
    log(f"Quality universe: {total_quality} | Already done: {total_quality - len(pending)} | Pending: {len(pending)}")
    log(f"{'=' * 60}")

    if not pending:
        log("Nothing to do — all tickers have integrated reports.")
        clear_state()
        return

    if dry_run:
        log("\nDRY RUN — would process these tickers:")
        for i, t in enumerate(pending, 1):
            log(f"  [{i}/{len(pending)}] {t}")
        return

    # Load state for retry tracking
    state = load_state()
    if "retries" not in state:
        state["retries"] = {}
    if "started" not in state:
        state["started"] = datetime.now().isoformat()
    save_state(state)

    usage_limit_wait = USAGE_LIMIT_FALLBACK_WAIT
    i = 0

    while i < len(pending):
        ticker = pending[i]

        # Skip if already completed (might have been done in a prior pass)
        if is_completed(ticker):
            log(f"[{i+1}/{len(pending)}] {ticker} — already done, skipping")
            i += 1
            continue

        retry_count = state["retries"].get(ticker, 0)
        if retry_count >= MAX_RETRIES_PER_TICKER:
            log(f"[{i+1}/{len(pending)}] {ticker} — skipping (failed {retry_count} times)")
            i += 1
            continue

        log(f"\n[{i+1}/{len(pending)}] {ticker} (attempt {retry_count + 1}/{MAX_RETRIES_PER_TICKER})")

        success, usage_limit_hit, output = run_analyze(ticker)

        if success:
            usage_limit_wait = USAGE_LIMIT_FALLBACK_WAIT  # reset fallback
            state["retries"].pop(ticker, None)
            state["last_completed"] = ticker
            state["last_completed_at"] = datetime.now().isoformat()
            save_state(state)
            i += 1

            # Breathing room between tickers
            if i < len(pending):
                log(f"  Waiting {BETWEEN_TICKERS_DELAY}s before next ticker...")
                time.sleep(BETWEEN_TICKERS_DELAY)

        elif usage_limit_hit:
            # Parse exact reset time from CLI output
            reset_seconds = parse_reset_duration(output)
            if reset_seconds:
                wait = reset_seconds
                log(f"  LIMIT Parsed reset time from CLI — waiting {wait}s ({wait//60}m {wait%60}s)")
            else:
                wait = usage_limit_wait
                log(f"  LIMIT Could not parse reset time — fallback wait {wait}s")
                usage_limit_wait = min(usage_limit_wait * 2, USAGE_LIMIT_MAX_WAIT)

            resume_at = datetime.now().timestamp() + wait
            resume_str = datetime.fromtimestamp(resume_at).strftime("%H:%M:%S")
            log(f"  Resuming at {resume_str}")
            # Don't increment i — retry same ticker after wait
            time.sleep(wait)

        else:
            # Non-usage-limit failure — increment retry count and move on
            state["retries"][ticker] = retry_count + 1
            save_state(state)
            log(f"  Moving to next ticker (will retry {ticker} later if retries remain)")
            i += 1
            time.sleep(BETWEEN_TICKERS_DELAY)

    # Final retry pass for failed tickers
    failed_tickers = [t for t in pending if not is_completed(t)]
    if failed_tickers:
        log(f"\n{'=' * 60}")
        log(f"RETRY PASS — {len(failed_tickers)} tickers still pending")
        log(f"{'=' * 60}")

        # Refresh pending list to catch any that were done
        pending = get_pending_tickers()

    # Summary
    now_done = total_quality - len(get_pending_tickers())
    still_pending = get_pending_tickers()

    log(f"\n{'=' * 60}")
    log(f"AMBIENT COMPLETE")
    log(f"Done: {now_done}/{total_quality} | Still pending: {len(still_pending)}")
    if still_pending:
        log(f"Pending: {', '.join(still_pending)}")
        log(f"Re-run this script to retry pending tickers.")
    else:
        clear_state()
        log("All tickers processed. State file cleared.")
    log(f"Duration: {state.get('started', '?')} → {datetime.now().isoformat()}")
    log(f"{'=' * 60}")


def show_status():
    """Show current progress without running anything."""
    pending = get_pending_tickers()
    total = len(get_quality_tickers())
    done = total - len(pending)

    state = load_state()

    print(f"\nAmbient Analyzer Status")
    print(f"{'=' * 40}")
    print(f"Progress: {done}/{total} ({done/total*100:.0f}%)")
    print(f"Pending:  {len(pending)}")

    if pending:
        print(f"\nPending tickers:")
        for t in pending:
            retries = state.get("retries", {}).get(t, 0)
            suffix = f" (failed {retries}x)" if retries > 0 else ""
            print(f"  {t}{suffix}")

    if state.get("last_completed"):
        print(f"\nLast completed: {state['last_completed']} at {state.get('last_completed_at', '?')}")
    if state.get("started"):
        print(f"Run started: {state['started']}")


def main():
    parser = argparse.ArgumentParser(
        description="Ambient /analyze runner — fire and forget"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be processed")
    parser.add_argument("--reset", action="store_true",
                        help="Clear state file and start fresh")
    parser.add_argument("--status", action="store_true",
                        help="Show progress without running")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.reset:
        clear_state()
        print("State reset. Run without --reset to start processing.")
    else:
        run_ambient(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
