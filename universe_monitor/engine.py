"""Universe Monitor — Main orchestrator.

Continuously cycles through all NSE-listed equities, runs 10 valuation
methods on each, stores reports + Excel summary, and emails bargain alerts.
"""

import time
from datetime import datetime

from shared.utils import logger
from shared.ticker_manager import (
    get_ticker_list, load_last_run, mark_completed,
    should_skip, load_failures, save_failure,
)
from shared.scraper import ScreenerScraper
from shared.data_parser import parse_company_page
from universe_monitor.valuation_engine import run_all_valuations
from universe_monitor.value_trap import detect_value_traps
from universe_monitor.report_writer import write_report
from universe_monitor.excel_summary import update_summary
from universe_monitor.email_alerter import send_batch_alert
from universe_monitor.ticker_excel import write_ticker_excel
from config import FULL_CYCLE_PAUSE_HOURS


def process_single(scraper, ticker, state, failures):
    """Process a single ticker. Returns (ticker, data, summary) or None."""
    if ticker in failures:
        return None

    html, variant = scraper.fetch_company_html(ticker)
    if html is None:
        logger.warning(f"{ticker}: Not found on Screener.in")
        save_failure(ticker, failures)
        return None

    data = parse_company_page(html, ticker)
    if not data.get("top_ratios"):
        logger.warning(f"{ticker}: No top ratios parsed, skipping")
        return None

    summary = run_all_valuations(data)

    trap = detect_value_traps(data)
    summary.value_trap_flags = trap.flags
    summary.value_trap_score = trap.score
    summary.value_trap_label = trap.label

    write_report(ticker, data, summary)
    update_summary(ticker, data, summary)
    write_ticker_excel(ticker, data, summary)
    mark_completed(ticker, state)

    return (ticker, data, summary) if summary.is_bargain else None


def run_cycle(tickers=None, skip_recent=True):
    """Run one full valuation cycle."""
    if tickers is None:
        tickers = get_ticker_list()
    total = len(tickers)
    logger.info(f"Starting cycle with {total} tickers")

    scraper = ScreenerScraper()
    state = load_last_run()
    failures = load_failures()
    bargains = []
    processed = 0
    skipped = 0
    errors = 0

    for i, ticker in enumerate(tickers):
        if skip_recent and should_skip(ticker, state, max_age_hours=24):
            skipped += 1
            continue

        logger.info(f"[{i+1}/{total}] Processing {ticker}...")
        try:
            result = process_single(scraper, ticker, state, failures)
            if result is not None:
                bargains.append(result)
                iv_display = result[2].composite_iv or result[2].median_iv
                logger.info(f"  BARGAIN FOUND: {ticker} ({result[2].sector}) \u2014 "
                            f"CMP \u20b9{result[2].cmp:,.2f}, "
                            f"IV \u20b9{iv_display:,.2f}, "
                            f"Upside {result[2].upside_pct*100:+.1f}%")
            processed += 1

        except Exception as e:
            logger.error(f"  Error processing {ticker}: {e}", exc_info=True)
            errors += 1
            continue

        if processed > 0 and processed % 50 == 0:
            logger.info(f"  Progress: {processed} processed, {skipped} skipped, "
                        f"{errors} errors, {len(bargains)} bargains so far")

    if bargains:
        logger.info(f"Cycle complete: {len(bargains)} bargains found. Sending alert...")
        send_batch_alert(bargains)
    else:
        logger.info("Cycle complete: No bargains found this round.")

    logger.info(f"Summary: {processed} processed, {skipped} skipped, "
                f"{errors} errors, {len(bargains)} bargains")


def run_continuous():
    """Run cycles in a loop with pauses between them."""
    while True:
        try:
            run_cycle()
            logger.info(f"Sleeping {FULL_CYCLE_PAUSE_HOURS}h before next cycle...")
            time.sleep(FULL_CYCLE_PAUSE_HOURS * 3600)
        except KeyboardInterrupt:
            logger.info("Stopped by user (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"Cycle failed: {e}", exc_info=True)
            logger.info("Retrying in 30 minutes...")
            time.sleep(1800)
