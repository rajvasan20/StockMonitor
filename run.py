"""
Stock Monitor — Unified CLI
============================

Usage:
    python run.py monitor                        # Full NSE universe scan (continuous)
    python run.py monitor --once                  # Single cycle, then exit
    python run.py monitor --test TCS,RELIANCE     # Test with specific tickers

    python run.py redflag-download                # Download NIFTY 50 annual reports
    python run.py redflag-download -c TCS,INFY    # Download specific companies
    python run.py redflag-notes -c TCS --year 2025  # Extract Notes to Accounts
    python run.py redflag-mda                     # Run MD&A extraction agent
    python run.py redflag-mda --ticker HCLTECH    # MD&A for one company

    python run.py analyze TRITURBINE                # Deep analysis (past-perf + valuation)
    python run.py analyze TRITURBINE --skill past-performance  # Past performance only
    python run.py analyze-batch                    # Deep analysis for all 43 quality cos
    python run.py analyze-batch --dry-run          # Preview what would run
    python run.py analyze-ambient                  # Fire-and-forget /analyze for all pending
    python run.py analyze-ambient --nifty50        # Nifty 50 only (skips already done)
    python run.py analyze-ambient --status         # Check progress

    python run.py integrity TCS                    # Management integrity report
    python run.py integrity TCS --from-year 2021    # Custom year range
    python run.py thesis TICKER                   # Generate 6-slider report

    python run.py theme list                      # List all themes
    python run.py theme screen data_center        # Screen a theme
    python run.py theme compare data_center "Cables & Wiring"  # Pairwise comparison
    python run.py technical TCS,RELIANCE          # Technical analysis
    python run.py shortterm data_center           # Short-term convergence screen
    python run.py shortterm --tickers TCS,POLYCAB # Short-term for specific tickers

    python run.py pptx TRITURBINE                  # Generate PPT for single company
    python run.py pptx-batch                      # Generate PPTs for all quality companies
    python run.py pptx-batch --tickers TCS,INFY   # Generate PPTs for specific tickers

    python run.py dashboard                       # Generate unified dashboard (all tabs)
    python run.py dashboard --test TCS,RELIANCE   # Test with specific tickers
    python run.py backtest                        # Run indicator backtests
"""

import sys
import os
import argparse
from datetime import datetime

# Ensure the project root is on sys.path so all imports resolve
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def cmd_monitor(args):
    """Run the Universe Monitor."""
    from shared.utils import logger
    from universe_monitor.engine import run_cycle, run_continuous

    logger.info("=" * 60)
    logger.info("Stock Monitor started")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    if args.test:
        tickers = [t.strip().upper() for t in args.test.split(",")]
        logger.info(f"Test mode: {tickers}")
        run_cycle(tickers=tickers, skip_recent=False)
    elif args.nifty500:
        from shared.ticker_manager import get_nifty500_list
        tickers = get_nifty500_list()
        logger.info(f"Nifty 500 mode: {len(tickers)} tickers")
        run_cycle(tickers=tickers, skip_recent=not args.fresh)
    elif args.once:
        run_cycle()
    else:
        run_continuous()


def cmd_redflag_download(args):
    """Download annual reports."""
    from red_flag.downloader import run
    companies = [c.strip().upper() for c in args.companies.split(",")] if args.companies else None
    run(
        companies=companies,
        from_year=args.from_year,
        to_year=args.to_year,
        delay=args.delay,
    )


def cmd_redflag_notes(args):
    """Extract Notes to Accounts."""
    from red_flag.notes_extractor import run
    companies = [c.strip().upper() for c in args.companies.split(",")]
    run(companies=companies, year=args.year)


def cmd_redflag_mda(args):
    """Run MD&A extraction agent."""
    from red_flag.mda_agent import run
    run(
        ticker=args.ticker,
        dry_run=args.dry_run,
        retry_failed=args.retry_failed,
    )


def cmd_analyze(args):
    """Run deep analysis (past-performance + valuation) via Claude API."""
    from scripts.analysis_agent import run
    run(
        ticker=args.ticker,
        skill=args.skill,
        dry_run=args.dry_run,
        force=args.force,
    )


def cmd_analyze_batch(args):
    """Run deep analysis for all quality companies."""
    from scripts.analysis_agent import run
    run(
        ticker=None,
        skill=args.skill,
        dry_run=args.dry_run,
        force=args.force,
    )


def cmd_analyze_ambient(args):
    """Run ambient /analyze — fire-and-forget, auto-retry on usage limits."""
    from scripts.ambient_analyzer import run_ambient, show_status, clear_state

    if args.status:
        show_status()
    elif args.reset:
        clear_state()
    else:
        tickers = args.tickers if hasattr(args, 'tickers') else None
        nifty50 = args.nifty50 if hasattr(args, 'nifty50') else False
        run_ambient(dry_run=args.dry_run, nifty50=nifty50, tickers=tickers)


def cmd_thesis(args):
    """Generate 5-slider investment thesis."""
    from shared.utils import logger
    from investment_thesis.builder import build_thesis

    tickers = [t.strip().upper() for t in args.ticker.split(",")]
    for ticker in tickers:
        path = build_thesis(ticker)
        if path:
            logger.info(f"Done: {path}")
        else:
            logger.error(f"Failed to build thesis for {ticker}")


def cmd_integrity(args):
    """Run management integrity analysis."""
    from shared.utils import logger
    from management_integrity.analyzer import run as integrity_run

    tickers = [t.strip().upper() for t in args.ticker.split(",")]
    for ticker in tickers:
        path = integrity_run(
            ticker,
            from_year=args.from_year,
            to_year=args.to_year,
            fresh=args.fresh,
        )
        if path:
            logger.info(f"Report: {path}")
        else:
            logger.error(f"Failed to generate integrity report for {ticker}")


def cmd_theme(args):
    """Thematic screening commands."""
    from shared.utils import logger

    if args.theme_command == "list":
        from themes.registry import get_all_themes
        themes = get_all_themes()
        print(f"\n{'='*60}")
        print(f"  THEMATIC WATCHLIST — {len(themes)} themes")
        print(f"{'='*60}\n")
        for slug, theme in themes.items():
            tickers = theme.all_tickers
            high = theme.high_exposure_tickers
            print(f"  {theme.name} [{slug}]")
            print(f"    {theme.description[:80]}...")
            print(f"    Horizon: {theme.investment_horizon}")
            print(f"    Stocks: {len(tickers)} total, {len(high)} high exposure")
            print(f"    Segments: {', '.join(s.name for s in theme.segments)}")
            print()

    elif args.theme_command == "screen":
        from themes.thematic_screener import screen_theme
        from themes.report_writer import save_thematic_report
        from themes.registry import get_theme
        slug = args.theme_slug
        results = screen_theme(slug)
        if not results:
            print(f"No results for theme '{slug}'")
            return

        print(f"\n{'='*70}")
        print(f"  THEMATIC SCREEN: {results[0].theme}")
        print(f"{'='*70}\n")
        print(f"{'Ticker':<12} {'Grade':<8} {'Exposure':<8} {'Checks':<8} "
              f"{'Verdict':<14} {'Trap':<12} {'Segment'}")
        print("-" * 90)
        for r in results:
            print(f"{r.ticker:<12} {r.grade} ({r.grade_label:<11}) "
                  f"{r.exposure:<8} {r.checks_passed}/{r.checks_total:<5} "
                  f"{r.verdict:<14} {r.value_trap_label:<12} {r.segment}")

        theme = get_theme(slug)
        path = save_thematic_report(results, theme.name, slug)
        print(f"\nReport saved: {path}")

    elif args.theme_command == "compare":
        from themes.thematic_screener import compare_within_segment
        slug = args.theme_slug
        segment = args.segment_name
        comparisons = compare_within_segment(slug, segment)
        if not comparisons:
            print(f"No comparison data for {slug} / {segment}")
            return

        print(f"\n{'='*70}")
        print(f"  PAIRWISE COMPARISON: {segment}")
        print(f"{'='*70}\n")
        for i, c in enumerate(comparisons):
            rank = i + 1
            print(f"\n  #{rank} {c['ticker']} ({c['name']}) — Exposure: {c['exposure']}")
            print(f"    Composite Rank: {c.get('composite_rank', 'N/A'):.1f}")
            print(f"    P/E: {c.get('pe', 'N/A')}  |  P/B: {c.get('pb', 'N/A')}")
            print(f"    PEG: {c.get('peg', 'N/A')}  |  EV/EBITDA: {c.get('ev_ebitda', 'N/A')}")
            print(f"    ROCE: {c.get('roce', 'N/A')}  |  ROE: {c.get('roe', 'N/A')}")
            print(f"    Rev CAGR 3Y: {c.get('revenue_cagr_3y', 'N/A')}")
            print(f"    D/E: {c.get('de_ratio', 'N/A')}  |  CR: {c.get('current_ratio', 'N/A')}")
            print(f"    Promoter: {c.get('promoter_holding', 'N/A')}%")
    else:
        print("Unknown theme command. Use: list, screen, compare")


def cmd_technical(args):
    """Run technical analysis on tickers."""
    from shared.utils import logger
    from technicals.signals import analyze_ticker
    from themes.report_writer import save_technical_report

    tickers = [t.strip().upper() for t in args.tickers.split(",")]
    signals = []

    print(f"\n{'='*70}")
    print(f"  TECHNICAL ANALYSIS — {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*70}\n")
    print(f"{'Ticker':<12} {'Action':<12} {'Score':>5} {'RSI':>6} "
          f"{'MACD':<18} {'CPR':<14} {'Volume':<16} {'Trend'}")
    print("-" * 100)

    for ticker in tickers:
        signal = analyze_ticker(ticker)
        signals.append(signal)
        if signal is None:
            print(f"{ticker:<12} {'NO DATA':<12}")
            continue

        rsi = f"{signal.rsi:.0f}" if signal.rsi else "N/A"
        print(f"{ticker:<12} {signal.action:<12} {signal.score:>+5d} "
              f"{rsi:>6} {signal.macd_signal:<18} "
              f"{signal.cpr_signal:<14} {signal.volume_signal:<16} "
              f"{signal.trend}")

        if signal.reasons:
            print(f"{'':>12} Reasons: {'; '.join(signal.reasons)}")

        # CPR levels
        if signal.cpr_pivot:
            print(f"{'':>12} CPR: S1={signal.cpr_s1:.2f} | "
                  f"BC={signal.cpr_bc:.2f} | P={signal.cpr_pivot:.2f} | "
                  f"TC={signal.cpr_tc:.2f} | R1={signal.cpr_r1:.2f}")
        print()

    path = save_technical_report(signals, args.tickers)
    print(f"Report saved: {path}")


def cmd_dashboard(args):
    """Generate unified single-page dashboard (all 5 tabs in one HTML)."""
    from shared.utils import logger
    from dashboard.unified import generate_unified_dashboard

    tickers = None
    if args.test:
        tickers = [t.strip().upper() for t in args.test.split(",")]
        logger.info(f"Dashboard test mode: {tickers}")

    filepath = generate_unified_dashboard(output_dir=args.output, tickers=tickers)
    print(f"\nDashboard generated: {filepath}")
    print(f"Open in browser to view.")


def cmd_dashboard_serve(args):
    """Serve the dashboard with live refresh support."""
    from dashboard.server import serve

    output_dir = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output", "dashboard"
    )
    tickers = None
    if args.test:
        tickers = [t.strip().upper() for t in args.test.split(",")]

    serve(output_dir=output_dir, tickers=tickers, port=args.port)


def cmd_backtest(args):
    """Run single-indicator backtest across Nifty 100."""
    from shared.utils import logger
    from dashboard.backtester import (
        run_backtest, format_backtest_report, backtest_to_json,
        run_pairwise_backtest, format_pairwise_report,
    )
    import json

    tickers = None
    if args.test:
        tickers = [t.strip().upper() for t in args.test.split(",")]
        logger.info(f"Backtest test mode: {tickers}")

    if args.pairs:
        # Pairwise combination backtest
        singles, pairs = run_pairwise_backtest(
            tickers=tickers,
            lookback_days=args.days,
            confluence_window=args.window,
        )
        report = format_pairwise_report(singles, pairs, args.window)
        print(report)
    else:
        # Single indicator backtest
        results = run_backtest(tickers=tickers, lookback_days=args.days)
        report = format_backtest_report(results)
        print(report)

        # Save JSON for dashboard integration
        from config import OUTPUT_DIR
        os.makedirs(os.path.join(OUTPUT_DIR, "dashboard"), exist_ok=True)
        json_path = os.path.join(OUTPUT_DIR, "dashboard", "backtest_results.json")
        with open(json_path, "w") as f:
            json.dump(backtest_to_json(results), f, indent=2)
        print(f"Results saved: {json_path}")


def cmd_pptx(args):
    """Generate PPT deck for a single company."""
    from shared.utils import logger
    from reports.pptx_generator import generate_pptx

    tickers = [t.strip().upper() for t in args.ticker.split(",")]
    for ticker in tickers:
        path = generate_pptx(ticker)
        if path:
            logger.info(f"PPT generated: {path}")
        else:
            logger.error(f"Failed to generate PPT for {ticker}")


def cmd_pptx_batch(args):
    """Generate PPT decks for all quality companies."""
    from shared.utils import logger
    from reports.pptx_generator import generate_batch_pptx

    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]

    results = generate_batch_pptx(tickers=tickers)
    print(f"\nBatch PPT Generation Complete")
    print(f"  Success: {len(results['success'])}")
    print(f"  Failed:  {len(results['failed'])}")
    if results['failed']:
        for ticker, reason in results['failed']:
            print(f"    {ticker}: {reason}")


def cmd_shortterm(args):
    """Run short-term convergence screen."""
    from shared.utils import logger
    from short_term.screener import (
        screen_tickers, screen_theme_short_term,
        format_convergence_report,
    )

    if args.theme_slug:
        results = screen_theme_short_term(args.theme_slug)
        title = f"Short-Term Screen: {args.theme_slug}"
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
        results = screen_tickers(tickers)
        title = "Short-Term Convergence Screen"
    else:
        print("Specify --theme or --tickers")
        return

    report = format_convergence_report(results, title=title)
    print(report)

    # Save report
    import os
    from config import OUTPUT_DIR
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    report_path = os.path.join(
        OUTPUT_DIR,
        f"shortterm_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"Report saved: {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Stock Monitor — NSE Universe Scanner, Red Flag Detector, Investment Thesis Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── monitor ──────────────────────────────────────────────────────────────
    p_mon = subparsers.add_parser("monitor", help="Scan all NSE equities (universe monitor)")
    p_mon.add_argument("--test", type=str, default=None,
                       help="Comma-separated tickers for test run (e.g. TCS,RELIANCE)")
    p_mon.add_argument("--once", action="store_true",
                       help="Run one cycle and exit (don't loop)")
    p_mon.add_argument("--nifty500", action="store_true",
                       help="Run only for Nifty 500 constituents")
    p_mon.add_argument("--fresh", action="store_true",
                       help="Ignore last_run cache (re-process all tickers)")

    # ── redflag-download ─────────────────────────────────────────────────────
    cy = datetime.now().year
    p_dl = subparsers.add_parser("redflag-download", help="Download annual reports (NIFTY 50)")
    p_dl.add_argument("--companies", "-c", type=str, default=None,
                      help="Comma-separated tickers (default: all NIFTY 50)")
    p_dl.add_argument("--from-year", type=int, default=cy - 5)
    p_dl.add_argument("--to-year", type=int, default=cy)
    p_dl.add_argument("--delay", "-d", type=float, default=1.5)

    # ── redflag-notes ────────────────────────────────────────────────────────
    p_notes = subparsers.add_parser("redflag-notes", help="Extract Notes to Accounts from PDFs")
    p_notes.add_argument("--companies", "-c", type=str, required=True,
                         help="Comma-separated tickers")
    p_notes.add_argument("--year", "-y", type=int, default=2025)

    # ── redflag-mda ──────────────────────────────────────────────────────────
    p_mda = subparsers.add_parser("redflag-mda", help="Extract MD&A context via Claude API")
    p_mda.add_argument("--ticker", type=str, default=None,
                       help="Process only this ticker")
    p_mda.add_argument("--dry-run", action="store_true",
                       help="Show what would be processed without API calls")
    p_mda.add_argument("--retry-failed", action="store_true",
                       help="Re-process previously failed PDFs")

    # ── analyze ──────────────────────────────────────────────────────────────
    p_analyze = subparsers.add_parser("analyze",
                                       help="Deep analysis (past-performance + valuation) via Claude API")
    p_analyze.add_argument("ticker", type=str,
                           help="Ticker symbol (e.g. TRITURBINE)")
    p_analyze.add_argument("--skill", type=str, default=None,
                           choices=["past-performance", "valuation"],
                           help="Run specific skill only (default: both)")
    p_analyze.add_argument("--dry-run", action="store_true",
                           help="Show what would be processed")
    p_analyze.add_argument("--force", action="store_true",
                           help="Re-run even if output exists")

    # ── analyze-batch ────────────────────────────────────────────────────────
    p_analyze_batch = subparsers.add_parser("analyze-batch",
                                             help="Deep analysis for all quality companies")
    p_analyze_batch.add_argument("--skill", type=str, default=None,
                                 choices=["past-performance", "valuation"],
                                 help="Run specific skill only (default: both)")
    p_analyze_batch.add_argument("--dry-run", action="store_true",
                                 help="Show what would be processed")
    p_analyze_batch.add_argument("--force", action="store_true",
                                 help="Re-run even if output exists")

    # ── analyze-ambient ─────────────────────────────────────────────────────
    p_ambient = subparsers.add_parser("analyze-ambient",
                                       help="Ambient /analyze — fire-and-forget, auto-retry on usage limits")
    p_ambient.add_argument("--dry-run", action="store_true",
                            help="Show what would be processed")
    p_ambient.add_argument("--status", action="store_true",
                            help="Show progress without running")
    p_ambient.add_argument("--reset", action="store_true",
                            help="Clear state and start fresh")
    p_ambient.add_argument("--nifty50", action="store_true",
                            help="Process only Nifty 50 tickers (skips already done)")
    p_ambient.add_argument("--tickers", nargs="+",
                            help="Process specific tickers (e.g. --tickers TCS INFY)")

    # ── integrity ────────────────────────────────────────────────────────────
    p_int = subparsers.add_parser("integrity",
                                   help="Management integrity analysis (guidance vs reality)")
    p_int.add_argument("ticker", type=str,
                       help="Ticker symbol(s), comma-separated (e.g. TCS,INFY)")
    p_int.add_argument("--from-year", type=int, default=None,
                       help="Start fiscal year (default: current year - 5)")
    p_int.add_argument("--to-year", type=int, default=None,
                       help="End fiscal year (default: current year)")
    p_int.add_argument("--fresh", action="store_true",
                       help="Re-extract even if cached files exist")

    # ── thesis ───────────────────────────────────────────────────────────────
    p_thesis = subparsers.add_parser("thesis", help="Generate 5-slider investment thesis")
    p_thesis.add_argument("ticker", type=str, help="Ticker symbol (e.g. TCS)")

    # ── theme ────────────────────────────────────────────────────────────────
    p_theme = subparsers.add_parser("theme", help="Thematic screening (value chain)")
    p_theme.add_argument("theme_command", type=str,
                         choices=["list", "screen", "compare"],
                         help="list | screen <slug> | compare <slug> <segment>")
    p_theme.add_argument("theme_slug", nargs="?", default=None,
                         help="Theme slug (data_center, defense, ev, semiconductor)")
    p_theme.add_argument("segment_name", nargs="?", default=None,
                         help="Segment name for compare command")

    # ── technical ────────────────────────────────────────────────────────────
    p_tech = subparsers.add_parser("technical",
                                    help="Technical analysis (RSI, MACD, CPR, Volume)")
    p_tech.add_argument("tickers", type=str,
                        help="Comma-separated tickers (e.g. TCS,RELIANCE,POLYCAB)")

    # ── pptx ─────────────────────────────────────────────────────────────────
    p_pptx = subparsers.add_parser("pptx",
                                    help="Generate 5-slider PPT for a company")
    p_pptx.add_argument("ticker", type=str,
                        help="Ticker symbol(s), comma-separated (e.g. TRITURBINE,CAMS)")

    # ── pptx-batch ───────────────────────────────────────────────────────────
    p_pptx_batch = subparsers.add_parser("pptx-batch",
                                          help="Generate PPTs for all quality companies")
    p_pptx_batch.add_argument("--tickers", type=str, default=None,
                              help="Comma-separated tickers (default: all quality universe)")

    # ── shortterm ────────────────────────────────────────────────────────────
    p_st = subparsers.add_parser("shortterm",
                                  help="Short-term convergence screen")
    p_st.add_argument("theme_slug", nargs="?", default=None,
                      help="Theme slug to screen (all tickers in theme)")
    p_st.add_argument("--tickers", type=str, default=None,
                      help="Comma-separated tickers (alternative to theme)")

    # ── dashboard ────────────────────────────────────────────────────────────
    p_dash = subparsers.add_parser("dashboard",
                                    help="Generate unified dashboard (all tabs, one HTML)")
    p_dash.add_argument("--test", type=str, default=None,
                        help="Comma-separated tickers for test run (e.g. TCS,RELIANCE)")
    p_dash.add_argument("--output", type=str, default=None,
                        help="Output directory for HTML file")

    # ── serve (dashboard with live refresh) ──────────────────────────
    p_serve = subparsers.add_parser("serve",
                                     help="Serve dashboard with live refresh button")
    p_serve.add_argument("--test", type=str, default=None,
                         help="Comma-separated tickers for test run")
    p_serve.add_argument("--output", type=str, default=None,
                         help="Output directory for HTML file")
    p_serve.add_argument("--port", type=int, default=8050,
                         help="Port to serve on (default: 8050)")

    # ── backtest ──────────────────────────────────────────────────────────────
    p_bt = subparsers.add_parser("backtest",
                                  help="Backtest individual technical indicators")
    p_bt.add_argument("--test", type=str, default=None,
                      help="Comma-separated tickers for test run")
    p_bt.add_argument("--days", type=int, default=365,
                      help="Lookback days (default: 365)")
    p_bt.add_argument("--pairs", action="store_true",
                      help="Run pairwise combination backtest")
    p_bt.add_argument("--window", type=int, default=3,
                      help="Confluence window in trading days (default: 3)")

    # ── Parse & dispatch ─────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    dispatch = {
        "monitor":          cmd_monitor,
        "redflag-download": cmd_redflag_download,
        "redflag-notes":    cmd_redflag_notes,
        "redflag-mda":      cmd_redflag_mda,
        "analyze":          cmd_analyze,
        "analyze-batch":    cmd_analyze_batch,
        "analyze-ambient":  cmd_analyze_ambient,
        "integrity":        cmd_integrity,
        "thesis":           cmd_thesis,
        "theme":            cmd_theme,
        "technical":        cmd_technical,
        "pptx":             cmd_pptx,
        "pptx-batch":       cmd_pptx_batch,
        "shortterm":        cmd_shortterm,
        "dashboard":        cmd_dashboard,
        "serve":            cmd_dashboard_serve,
        "backtest":         cmd_backtest,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
