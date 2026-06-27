"""Unified Dashboard — single HTML, all tabs, one data fetch.

Fetches OHLCV data ONCE per ticker and runs all four analyses:
  1. Technical Signals
  2. Money Flow
  3. Trade Planner
  4. Opportunities

Fixes the consistency gap: any stock that is ENTER in Trade Planner
automatically qualifies for the Opportunities tab (ranked by conviction).

Usage:
    python run.py unified
    python run.py unified --test TCS,RELIANCE
"""

import os
import json
import time
import random
from datetime import datetime, timezone, timedelta
from dataclasses import asdict
from typing import Optional, List, Dict

import pandas as pd
import numpy as np

from technicals.indicators import compute_all_indicators
from technicals.data_fetcher import fetch_daily_ohlcv, purge_old_cache
from dashboard.nifty100 import NIFTY_100
from dashboard.sectors import get_sector_industry
from dashboard.generator import analyze_for_dashboard, _signal_to_dict as tech_to_dict
from dashboard.money_flow import (
    analyze_money_flow, fetch_fii_dii_flows,
    _signal_to_dict as mf_to_dict,
)
from dashboard.trade_planner import (
    build_trade_plan, compute_market_regime, _plan_to_dict,
)
from dashboard.opportunities import (
    build_opportunity, _conviction_score, _opp_to_dict,
    MAX_BUY_OPPORTUNITIES, MAX_SELL_OPPORTUNITIES,
)
from dashboard.vinoth_strategy import (
    scan_strategy, signal_to_dict as strategy_to_dict,
    STRATEGY_WIN_RATE_20D, STRATEGY_AVG_RETURN_20D,
    STRATEGY_WIN_RATE_10D, STRATEGY_AVG_RETURN_10D,
    STRATEGY_CROSSOVER_PROB,
)
from dashboard.action_brief import build_action_brief
from dashboard.flow_tracker import (
    _fetch_all_bhavcopy, _compute_flow_indicators,
    _aggregate_fii_dii, _group_deals_by_ticker,
)
from short_term.nse_events import fetch_bulk_deals, fetch_block_deals
from shared.utils import logger

IST = timezone(timedelta(hours=5, minutes=30))
NIFTY50_SYMBOL = "^NSEI"


def generate_unified_dashboard(output_dir: str = None,
                                tickers: List[str] = None) -> str:
    """Generate a single unified HTML dashboard with all tabs.

    Key improvement over separate generation:
    - Data fetched ONCE per ticker (not 4x)
    - Consistent filtering across tabs
    - Single file output
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  "output", "dashboard")
    os.makedirs(output_dir, exist_ok=True)

    if tickers is None:
        tickers = NIFTY_100

    # ── Purge stale cache files ─────────────────────────────────
    purge_old_cache(max_age_days=7)
    from shared.utils import purge_daily_cache
    purge_daily_cache(max_age_days=7)

    # ── Fetch benchmark ONCE ─────────────────────────────────────
    benchmark_df = None
    try:
        import yfinance as yf
        benchmark_df = yf.download(NIFTY50_SYMBOL, period="1y",
                                    progress=False, auto_adjust=True)
        if benchmark_df is not None and isinstance(benchmark_df.columns, pd.MultiIndex):
            benchmark_df.columns = benchmark_df.columns.get_level_values(0)
        if benchmark_df is not None and len(benchmark_df) > 0:
            logger.info(f"Benchmark: {len(benchmark_df)} days of Nifty 50")
        else:
            benchmark_df = None
    except Exception as e:
        logger.warning(f"Benchmark fetch failed: {e}")

    # ── Market regime (computed once) ────────────────────────────
    regime, regime_desc = compute_market_regime(benchmark_df)
    logger.info(f"Market regime: {regime} — {regime_desc}")

    # ── FII/DII flows ────────────────────────────────────────────
    fii_dii = fetch_fii_dii_flows()

    # ── Load backtest results if available ───────────────────────
    backtest_data = None
    bt_path = os.path.join(output_dir, "backtest_results.json")
    if os.path.exists(bt_path):
        with open(bt_path, "r") as f:
            backtest_data = json.load(f)
        logger.info(f"Loaded backtest results from {bt_path}")

    # ── Analyze all tickers (ONE fetch per ticker) ───────────────
    logger.info(f"Unified Dashboard: analyzing {len(tickers)} tickers...")

    tech_signals = []
    mf_signals = []
    trade_plans = []
    all_opps = []
    strategy_signals = []
    failed = []
    sector_buy_counts: Dict[str, int] = {}

    for i, ticker in enumerate(tickers):
        logger.info(f"[{i+1}/{len(tickers)}] {ticker}...")
        try:
            # SINGLE fetch per ticker
            df = fetch_daily_ohlcv(ticker, days=365)
            if df is None:
                failed.append(ticker)
                continue

            # Tab 1: Technical Signals
            tech_sig = analyze_for_dashboard(ticker, df.copy(),
                                             benchmark_df=benchmark_df)
            if tech_sig:
                tech_signals.append(tech_sig)

            # Tab 2: Money Flow
            mf_sig = analyze_money_flow(ticker, df.copy())
            if mf_sig:
                mf_signals.append(mf_sig)

            # Tab 3: Trade Planner
            plan = build_trade_plan(ticker, df.copy(), benchmark_df,
                                    regime, regime_desc)
            if plan:
                trade_plans.append(plan)

            # Tab 4: Opportunities
            opp = build_opportunity(ticker, df.copy(), benchmark_df,
                                    sector_buy_counts)
            if opp:
                all_opps.append(opp)
                if opp.side == "BUY" and opp.tech_score >= 3:
                    sector_buy_counts[opp.sector] = \
                        sector_buy_counts.get(opp.sector, 0) + 1

            # Tab 6: Vinoth's Strategy
            strat_sig = scan_strategy(ticker, df.copy())
            if strat_sig:
                strategy_signals.append(strat_sig)

            if not tech_sig and not mf_sig and not plan:
                failed.append(ticker)

        except Exception as e:
            logger.error(f"Failed {ticker}: {e}")
            failed.append(ticker)

        # Rate limiting
        if i < len(tickers) - 1:
            time.sleep(0.3 + random.uniform(0, 0.2))

    logger.info(f"Unified: {len(tech_signals)} tech, {len(mf_signals)} flow, "
                f"{len(trade_plans)} plans, {len(all_opps)} opps, "
                f"{len(failed)} failed")

    # ── Flow Tracker data (Tab 5) ────────────────────────────────
    logger.info("Flow Tracker: fetching bhavcopy delivery data...")
    tickers_set = set(tickers)
    all_delivery = _fetch_all_bhavcopy(tickers_set, days=30)

    logger.info("Flow Tracker: fetching bulk/block deals...")
    bulk_deals = fetch_bulk_deals()
    block_deals = fetch_block_deals()
    deals_by_ticker = _group_deals_by_ticker(bulk_deals, block_deals)

    logger.info("Flow Tracker: computing flow indicators & market cap...")
    from shared.utils import daily_cache_get, daily_cache_set
    flow_indicators_by_ticker: Dict[str, dict] = {}
    mcap_by_ticker: Dict[str, Optional[float]] = {}

    # Try loading market cap from daily cache
    cached_mcap = daily_cache_get("mcap_nifty100")
    if cached_mcap:
        mcap_by_ticker = cached_mcap

    for ticker in tickers:
        try:
            # Reuse cached OHLCV (already fetched in main loop above)
            df = fetch_daily_ohlcv(ticker, days=90)
            if df is not None and len(df) >= 50:
                flow_indicators_by_ticker[ticker] = _compute_flow_indicators(df)
            else:
                flow_indicators_by_ticker[ticker] = {}

            # Market cap — only fetch if not in cache
            if ticker not in mcap_by_ticker or mcap_by_ticker[ticker] is None:
                try:
                    import yfinance as yf
                    symbol = f"{ticker}.NS"
                    mcap = yf.Ticker(symbol).fast_info.market_cap
                    mcap_by_ticker[ticker] = round(mcap / 1e7, 0) if mcap and mcap > 0 else None
                except Exception:
                    mcap_by_ticker[ticker] = None
        except Exception:
            flow_indicators_by_ticker[ticker] = {}
            if ticker not in mcap_by_ticker:
                mcap_by_ticker[ticker] = None

    # Cache market cap for today
    if not cached_mcap:
        daily_cache_set("mcap_nifty100", mcap_by_ticker)

    # Build flow tracker stocks payload
    flow_stocks = {}
    for ticker in tickers:
        daily = all_delivery.get(ticker, [])
        if not daily:
            continue
        sector, industry = get_sector_industry(ticker)
        last_close = daily[-1]["close"] if daily else None
        last_change = daily[-1].get("change_pct") if daily else None
        flow_stocks[ticker] = {
            "sector": sector or "Unknown",
            "industry": industry or "",
            "mcap_cr": mcap_by_ticker.get(ticker),
            "last_close": last_close,
            "last_change": last_change,
            "daily_data": daily,
            "deals": deals_by_ticker.get(ticker, []),
            "flow_indicators": flow_indicators_by_ticker.get(ticker, {}),
        }
    flow_tickers = sorted(flow_stocks.keys())
    fii_dii_agg = _aggregate_fii_dii(fii_dii)

    flow_payload = {
        "tickers": flow_tickers,
        "stocks": flow_stocks,
        "fii_dii": fii_dii_agg,
    }
    logger.info(f"Flow Tracker: {len(flow_stocks)} stocks with delivery data")

    # ── Sort each dataset ────────────────────────────────────────
    tech_signals.sort(key=lambda s: s.score, reverse=True)
    mf_signals.sort(key=lambda s: s.money_flow_score, reverse=True)
    trade_plans.sort(key=lambda p: p.combined_score, reverse=True)

    # ── CONSISTENCY FIX: Opportunities includes TradePlanner ENTER ─
    enter_tickers = {p.ticker for p in trade_plans if p.action == "ENTER"}

    buy_opps = [o for o in all_opps if o.side == "BUY" and
                (o.tech_score >= 3 or
                 (o.alignment == "strong" and o.tech_score >= 1) or
                 o.ticker in enter_tickers) and
                # Quality gates — skip trades with negative expected value
                (o.risk_reward is not None and o.risk_reward >= 1.5) and
                (o.target_pct is not None and o.target_pct >= 2.0) and
                (o.change_20d is None or o.change_20d <= 15)]

    sell_opps = [o for o in all_opps if o.side == "SELL" or
                 (o.tech_score <= -3 and o.flow_score <= -1)]

    # Money Leading watchlist — Category 2: MF strong but technicals haven't triggered
    money_leading = [o for o in all_opps if o.side == "BUY" and
                     o.signal_category == "early" and
                     o not in buy_opps]
    money_leading.sort(key=lambda o: o.flow_score, reverse=True)
    money_leading = money_leading[:10]

    buy_opps.sort(key=_conviction_score, reverse=True)
    sell_opps.sort(key=_conviction_score, reverse=True)
    buy_opps = buy_opps[:MAX_BUY_OPPORTUNITIES]
    sell_opps = sell_opps[:MAX_SELL_OPPORTUNITIES]

    # ── Sector concentration for Trade Planner ───────────────────
    sector_counts = {}
    for p in trade_plans:
        if p.action == "ENTER":
            sector_counts[p.sector] = sector_counts.get(p.sector, 0) + 1

    # ── Action Brief (synthesized decision view) ──────────────────
    action_brief = build_action_brief(
        regime=regime,
        regime_desc=regime_desc,
        fii_dii=fii_dii,
        trade_plans=trade_plans,
        buy_opps=buy_opps,
        sell_opps=sell_opps,
        strategy_signals=strategy_signals,
        tech_signals=tech_signals,
        mf_signals=mf_signals,
    )

    # ── Build unified HTML ───────────────────────────────────────
    now_ist = datetime.now(IST)
    html = _build_unified_html(
        tech_signals=tech_signals,
        mf_signals=mf_signals,
        trade_plans=trade_plans,
        buy_opps=buy_opps,
        sell_opps=sell_opps,
        money_leading=money_leading,
        strategy_signals=strategy_signals,
        fii_dii=fii_dii,
        backtest_data=backtest_data,
        regime=regime,
        regime_desc=regime_desc,
        sector_counts=sector_counts,
        generated_at=now_ist,
        failed=failed,
        total_analyzed=len(tech_signals),
        flow_payload=flow_payload,
        action_brief=action_brief,
    )

    filepath = os.path.join(output_dir, "unified_dashboard.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Unified dashboard saved: {filepath}")
    return filepath


def _build_unified_html(tech_signals, mf_signals, trade_plans,
                         buy_opps, sell_opps, money_leading,
                         strategy_signals,
                         fii_dii, backtest_data,
                         regime, regime_desc, sector_counts,
                         generated_at, failed, total_analyzed,
                         flow_payload=None, action_brief=None):
    """Build the single-page unified HTML dashboard."""

    # Serialize all data to JSON
    brief_json = json.dumps(action_brief or {}, indent=None)
    tech_json = json.dumps([tech_to_dict(s) for s in tech_signals], indent=None)
    mf_json = json.dumps([mf_to_dict(s) for s in mf_signals], indent=None)
    plans_json = json.dumps([_plan_to_dict(p) for p in trade_plans], indent=None)
    buy_json = json.dumps([_opp_to_dict(o) for o in buy_opps], indent=None)
    sell_json = json.dumps([_opp_to_dict(o) for o in sell_opps], indent=None)
    ml_json = json.dumps([_opp_to_dict(o) for o in money_leading], indent=None)

    # Strategy signals — group by zone
    entry_zone = [s for s in strategy_signals if s.zone == "entry"]
    near_zone = [s for s in strategy_signals if s.zone == "near"]
    crossed_zone = [s for s in strategy_signals if s.zone == "crossed"]
    entry_zone.sort(key=lambda s: s.rsi or 100)  # lowest RSI first
    near_zone.sort(key=lambda s: s.rsi or 100)
    crossed_zone.sort(key=lambda s: s.days_since_cross or 0)
    strat_entry_json = json.dumps([strategy_to_dict(s) for s in entry_zone], indent=None)
    strat_near_json = json.dumps([strategy_to_dict(s) for s in near_zone], indent=None)
    strat_crossed_json = json.dumps([strategy_to_dict(s) for s in crossed_zone], indent=None)
    fii_json = json.dumps(fii_dii or [], indent=None)
    bt_json = json.dumps(backtest_data or [], indent=None)
    sector_json = json.dumps(sector_counts, indent=None)
    flow_json = json.dumps(flow_payload or {"tickers":[],"stocks":{},"fii_dii":{}}, default=str, indent=None)

    # Summary stats
    tech_summary = {
        'strong_buy': sum(1 for s in tech_signals if s.action == 'STRONG BUY'),
        'buy': sum(1 for s in tech_signals if s.action == 'BUY'),
        'watch': sum(1 for s in tech_signals if s.action == 'WATCH'),
        'hold': sum(1 for s in tech_signals if s.action == 'HOLD'),
        'sell': sum(1 for s in tech_signals if s.action == 'SELL'),
        'strong_sell': sum(1 for s in tech_signals if s.action == 'STRONG SELL'),
    }

    enter_count = sum(1 for p in trade_plans if p.action == "ENTER")
    wait_count = sum(1 for p in trade_plans if p.action == "WAIT")
    avoid_count = sum(1 for p in trade_plans if p.action == "AVOID")
    exit_count = sum(1 for p in trade_plans if p.action == "EXIT")

    regime_icons = {"bull": "\u25B2", "bear": "\u25BC", "sideways": "\u25AC"}
    regime_icon = regime_icons.get(regime, "?")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock Monitor — Unified Dashboard — {generated_at.strftime('%d %b %Y')}</title>
<style>
{_get_unified_css()}
</style>
</head>
<body>

<header>
    <div class="header-content">
        <div class="header-top">
            <h1>Nifty 100 Stock Monitor</h1>
            <button id="refreshBtn" class="refresh-btn" onclick="refreshDashboard()" title="Refresh data">
                <svg class="refresh-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="23 4 23 10 17 10"></polyline>
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                </svg>
                <span id="refreshLabel">Refresh</span>
            </button>
        </div>
        <div class="header-meta">
            <span class="gen-time" id="genTime">Generated: {generated_at.strftime('%d %b %Y, %I:%M %p IST')}</span>
            <span class="stock-count">{total_analyzed} stocks analyzed</span>
            {f'<span class="failed-count">{len(failed)} failed</span>' if failed else ''}
        </div>
    </div>
    <nav class="tab-bar">
        <button class="tab active" data-tab="actionbrief">Action Brief</button>
        <button class="tab" data-tab="technical">Technical Signals</button>
        <button class="tab" data-tab="moneyflow">Money Flow</button>
        <button class="tab" data-tab="tradeplanner">Trade Planner</button>
        <button class="tab" data-tab="opportunities">Opportunities</button>
        <button class="tab" data-tab="flowtracker">Flow Tracker</button>
        <button class="tab" data-tab="strategy">Vinoth's Strategy</button>
    </nav>
</header>

<div class="container">

<!-- ══════════════════════════════════════════════════════════════ -->
<!-- TAB 0: ACTION BRIEF                                            -->
<!-- ══════════════════════════════════════════════════════════════ -->
<div id="tab-actionbrief" class="tab-content active">
    <div id="actionBriefContent"></div>
</div>

<!-- ══════════════════════════════════════════════════════════════ -->
<!-- TAB 1: TECHNICAL SIGNALS                                      -->
<!-- ══════════════════════════════════════════════════════════════ -->
<div id="tab-technical" class="tab-content">

    <div class="summary-grid six-col">
        <div class="summary-card strong-buy"><div class="card-value">{tech_summary['strong_buy']}</div><div class="card-label">Strong Buy</div></div>
        <div class="summary-card buy"><div class="card-value">{tech_summary['buy']}</div><div class="card-label">Buy</div></div>
        <div class="summary-card watch"><div class="card-value">{tech_summary['watch']}</div><div class="card-label">Watch</div></div>
        <div class="summary-card hold"><div class="card-value">{tech_summary['hold']}</div><div class="card-label">Hold</div></div>
        <div class="summary-card sell"><div class="card-value">{tech_summary['sell']}</div><div class="card-label">Sell</div></div>
        <div class="summary-card strong-sell"><div class="card-value">{tech_summary['strong_sell']}</div><div class="card-label">Strong Sell</div></div>
    </div>

    <div class="filters">
        <div class="filter-group"><label>Action:</label>
            <select id="tech-actionFilter"><option value="all">All</option><option value="STRONG BUY">Strong Buy</option><option value="BUY">Buy</option><option value="WATCH">Watch</option><option value="HOLD">Hold</option><option value="SELL">Sell</option><option value="STRONG SELL">Strong Sell</option></select>
        </div>
        <div class="filter-group"><label>Search:</label><input type="text" id="tech-search" placeholder="Ticker..."></div>
        <div class="filter-group"><label>Min Score:</label><input type="number" id="tech-minScore" placeholder="-16 to 16" min="-16" max="16"></div>
    </div>

    <div class="table-wrapper"><table id="techTable"><thead><tr>
        <th class="sortable" data-col="ticker" data-tab="tech">Ticker</th>
        <th class="sortable" data-col="close" data-tab="tech">Close</th>
        <th class="sortable" data-col="change_1d" data-tab="tech">1D %</th>
        <th class="sortable" data-col="change_5d" data-tab="tech">5D %</th>
        <th class="sortable" data-col="change_20d" data-tab="tech">20D %</th>
        <th class="sortable" data-col="rsi" data-tab="tech">RSI</th>
        <th class="sortable" data-col="macd_signal" data-tab="tech">MACD</th>
        <th class="sortable" data-col="bb_signal" data-tab="tech">Bollinger</th>
        <th class="sortable" data-col="volume_ratio" data-tab="tech">Vol Ratio</th>
        <th class="sortable" data-col="ema_cross_signal" data-tab="tech">EMA 20/50</th>
        <th class="sortable" data-col="vwap_signal" data-tab="tech">VWAP</th>
        <th class="sortable" data-col="rs_signal" data-tab="tech">RS vs Nifty</th>
        <th class="sortable" data-col="trend" data-tab="tech">Trend</th>
        <th class="sortable" data-col="score" data-tab="tech">Score</th>
        <th class="sortable" data-col="action" data-tab="tech">Action</th>
    </tr></thead><tbody id="techBody"></tbody></table></div>
</div>

<!-- ══════════════════════════════════════════════════════════════ -->
<!-- TAB 2: MONEY FLOW                                             -->
<!-- ══════════════════════════════════════════════════════════════ -->
<div id="tab-moneyflow" class="tab-content">

    <div class="section-title">Market-Level Flow (FII / DII)</div>
    <div id="fiiDiiSection" class="fii-dii-grid"></div>

    <div class="filters">
        <div class="filter-group"><label>Flow:</label>
            <select id="mf-flowFilter"><option value="all">All</option><option value="STRONG BUY">Strong Buy</option><option value="BUY">Buy</option><option value="WATCH">Watch</option><option value="HOLD">Hold</option><option value="AVOID">Avoid</option><option value="SELL">Sell</option></select>
        </div>
        <div class="filter-group"><label>Search:</label><input type="text" id="mf-search" placeholder="Ticker..."></div>
        <div class="filter-group"><label>Min Score:</label><input type="number" id="mf-minScore" placeholder="-10 to 10" min="-10" max="10"></div>
    </div>

    <div class="table-wrapper"><table id="mfTable"><thead><tr>
        <th class="sortable" data-col="ticker" data-tab="mf">Ticker</th>
        <th class="sortable" data-col="close" data-tab="mf">Close</th>
        <th class="sortable" data-col="change_1d" data-tab="mf">1D %</th>
        <th class="sortable" data-col="mfi" data-tab="mf">MFI</th>
        <th class="sortable" data-col="cmf" data-tab="mf">CMF</th>
        <th class="sortable" data-col="obv_trend" data-tab="mf">OBV</th>
        <th class="sortable" data-col="obv_divergence" data-tab="mf">Divergence</th>
        <th class="sortable" data-col="vol_ratio" data-tab="mf">Vol Ratio</th>
        <th class="sortable" data-col="vol_trend_5d" data-tab="mf">Vol 5D %</th>
        <th class="sortable" data-col="accumulation_signal" data-tab="mf">Pattern</th>
        <th class="sortable" data-col="money_flow_score" data-tab="mf">Score</th>
        <th class="sortable" data-col="action" data-tab="mf">Flow</th>
    </tr></thead><tbody id="mfBody"></tbody></table></div>
</div>

<!-- ══════════════════════════════════════════════════════════════ -->
<!-- TAB 3: TRADE PLANNER                                          -->
<!-- ══════════════════════════════════════════════════════════════ -->
<div id="tab-tradeplanner" class="tab-content">

    <div class="regime-banner regime-{regime}">
        <div class="regime-icon">{regime_icon}</div>
        <div class="regime-text">
            <div class="regime-label">MARKET REGIME</div>
            <div class="regime-desc">{regime_desc}</div>
        </div>
        {'<div class="regime-warning">BUY signals suppressed in bear market</div>' if regime == "bear" else ""}
    </div>

    <div class="capital-bar">
        <div class="capital-group"><label>Capital (&#x20B9;):</label><input type="number" id="capitalInput" value="1000000" min="10000" step="100000"></div>
        <div class="capital-group"><label>Risk/trade:</label>
            <select id="riskPct"><option value="0.5">0.5%</option><option value="1" selected>1%</option><option value="1.5">1.5%</option><option value="2">2%</option></select>
        </div>
        <div class="capital-info">Max risk/trade: <span id="maxRiskDisplay">&#x20B9;10,000</span></div>
    </div>

    <div class="summary-grid four-col">
        <div class="summary-card enter-card"><div class="card-value">{enter_count}</div><div class="card-label">Enter</div></div>
        <div class="summary-card wait-card"><div class="card-value">{wait_count}</div><div class="card-label">Wait</div></div>
        <div class="summary-card avoid-card"><div class="card-value">{avoid_count}</div><div class="card-label">Avoid</div></div>
        <div class="summary-card exit-card"><div class="card-value">{exit_count}</div><div class="card-label">Exit</div></div>
    </div>

    <div class="section-title">Sector Concentration (ENTER signals)</div>
    <div id="sectorHeatmap" class="sector-heatmap"></div>

    <div class="filters">
        <div class="filter-group"><label>Action:</label>
            <select id="tp-actionFilter"><option value="all">All</option><option value="ENTER" selected>Enter Only</option><option value="WAIT">Wait</option><option value="AVOID">Avoid</option><option value="EXIT">Exit</option></select>
        </div>
        <div class="filter-group"><label>Search:</label><input type="text" id="tp-search" placeholder="Ticker..."></div>
        <div class="filter-group"><label>Sector:</label><select id="tp-sectorFilter"><option value="all">All Sectors</option></select></div>
        <div class="filter-group"><label>Min R:R:</label><input type="number" id="tp-minRR" value="1.5" min="0" step="0.5"></div>
    </div>

    <div class="table-wrapper"><table id="planTable"><thead><tr>
        <th class="sortable" data-col="ticker" data-tab="tp">Ticker</th>
        <th class="sortable" data-col="sector" data-tab="tp">Sector</th>
        <th class="sortable" data-col="close" data-tab="tp">Close</th>
        <th class="sortable" data-col="combined_score" data-tab="tp">Score</th>
        <th class="sortable" data-col="technical_score" data-tab="tp">Tech</th>
        <th class="sortable" data-col="money_flow_score" data-tab="tp">Flow</th>
        <th class="sortable" data-col="stop_loss" data-tab="tp">Stop Loss</th>
        <th class="sortable" data-col="target" data-tab="tp">Target</th>
        <th class="sortable" data-col="risk_reward" data-tab="tp">R:R</th>
        <th>Qty</th>
        <th>Risk Amt</th>
        <th class="sortable" data-col="dist_from_52w_high" data-tab="tp">vs 52W H</th>
        <th class="sortable" data-col="action" data-tab="tp">Action</th>
    </tr></thead><tbody id="planBody"></tbody></table></div>
</div>

<!-- ══════════════════════════════════════════════════════════════ -->
<!-- TAB 4: OPPORTUNITIES                                          -->
<!-- ══════════════════════════════════════════════════════════════ -->
<div id="tab-opportunities" class="tab-content">

    <div class="regime-banner regime-{regime}">
        <div class="regime-icon">{regime_icon}</div>
        <div class="regime-text">
            <div class="regime-label">MARKET REGIME</div>
            <div class="regime-desc">{regime_desc}</div>
        </div>
        {'<div class="regime-warning">Bear market — prioritize capital preservation</div>' if regime == "bear" else ""}
    </div>

    <div class="capital-bar">
        <div class="capital-group"><label>Capital (&#x20B9;):</label><input type="number" id="opp-capitalInput" value="1000000" min="10000" step="100000"></div>
        <div class="capital-group"><label>Risk/trade:</label>
            <select id="opp-riskPct"><option value="0.5">0.5%</option><option value="1" selected>1%</option><option value="1.5">1.5%</option><option value="2">2%</option></select>
        </div>
        <div class="capital-info">Max risk/trade: <span id="opp-maxRiskDisplay">&#x20B9;10,000</span></div>
    </div>

    <div class="section-header buy-section">
        <h2>BUY Opportunities ({len(buy_opps)})</h2>
        <p class="section-sub">Strongest conviction bullish setups — includes all Trade Planner ENTER signals</p>
    </div>
    <div id="buyCards"></div>

    <div class="section-header sell-section">
        <h2>SELL / EXIT Signals ({len(sell_opps)})</h2>
        <p class="section-sub">Stocks showing bearish conviction</p>
    </div>
    <div id="sellCards"></div>

    <div class="section-header ml-section" style="margin-top:32px;border-left:4px solid #1f6feb;background:linear-gradient(135deg,rgba(31,111,235,0.08),rgba(31,111,235,0.02))">
        <h2>Money Leading — Watchlist ({len(money_leading)})</h2>
        <p class="section-sub">Smart money flowing in, technicals haven't triggered yet — potential future BUY setups</p>
    </div>
    <div id="mlCards"></div>
</div>

<!-- ══════════════════════════════════════════════════════════════ -->
<!-- TAB 5: FLOW TRACKER                                           -->
<!-- ══════════════════════════════════════════════════════════════ -->
<div id="tab-flowtracker" class="tab-content">

    <div class="ft-header">
        <div class="ft-header-row">
            <div class="ft-stock-select-wrap">
                <select class="ft-stock-select" id="ftStockSelect"></select>
            </div>
            <div id="ftStockMeta" class="ft-stock-meta"></div>
            <div id="ftPriceBlock" class="ft-price-block"></div>
        </div>
    </div>

    <div class="ft-toolbar">
        <span class="ft-toolbar-label">Period:</span>
        <button class="ft-filter-btn active" onclick="ftSetFilter('day', this)">Day</button>
        <button class="ft-filter-btn" onclick="ftSetFilter('week', this)">Week</button>
        <button class="ft-filter-btn" onclick="ftSetFilter('month', this)">Month</button>
        <input class="ft-search-input" id="ftSearchInput" type="text" placeholder="Search ticker..." oninput="ftFilterTickers(this.value)">
    </div>

    <div class="ft-summary-row" id="ftSummaryCards"></div>

    <div class="ft-content-grid">
        <div class="ft-card ft-full-width">
            <div class="ft-card-header">Market Context — FII/DII Flows (Aggregate)</div>
            <div class="ft-card-body" id="ftFiiDiiContext"></div>
        </div>

        <div class="ft-card">
            <div class="ft-card-header">Delivery Ranking — Top Absorbed (Month)</div>
            <div class="ft-card-body ft-rank-table" id="ftRankTable"></div>
        </div>

        <div class="ft-card">
            <div class="ft-card-header">Bulk/Block Deals — Nifty 100</div>
            <div class="ft-card-body ft-rank-table" id="ftDealsPanel"></div>
        </div>

        <div class="ft-card ft-full-width">
            <div class="ft-card-header">Daily Delivery Breakdown</div>
            <div class="ft-card-body">
                <div class="ft-table-scroll" id="ftDailyTable"></div>
            </div>
        </div>
    </div>
</div>

<!-- ══════════════════════════════════════════════════════════════ -->
<!-- TAB 6: VINOTH'S STRATEGY                                       -->
<!-- ══════════════════════════════════════════════════════════════ -->
<div id="tab-strategy" class="tab-content">
    <div class="vs-header">
        <div class="vs-title">RSI Oversold + MACD Convergence</div>
        <div class="vs-subtitle">Enter when RSI <= 35 and MACD histogram is converging. 95% chance of crossover within 15 days.</div>
        <div class="vs-stats-row">
            <div class="vs-stat"><div class="vs-stat-val vs-green">{STRATEGY_WIN_RATE_20D}%</div><div class="vs-stat-label">20D Win Rate</div></div>
            <div class="vs-stat"><div class="vs-stat-val vs-green">+{STRATEGY_AVG_RETURN_20D}%</div><div class="vs-stat-label">20D Avg Return</div></div>
            <div class="vs-stat"><div class="vs-stat-val vs-blue">{STRATEGY_WIN_RATE_10D}%</div><div class="vs-stat-label">10D Win Rate</div></div>
            <div class="vs-stat"><div class="vs-stat-val vs-blue">+{STRATEGY_AVG_RETURN_10D}%</div><div class="vs-stat-label">10D Avg Return</div></div>
            <div class="vs-stat"><div class="vs-stat-val vs-yellow">{STRATEGY_CROSSOVER_PROB}%</div><div class="vs-stat-label">Crossover Prob</div></div>
        </div>
        <div class="vs-rule">Rule: Enter at convergence. Time-stop if MACD doesn't cross within 10 days. Hold 20 days.</div>
    </div>

    <div class="section-header" style="border-left:4px solid #f85149;background:linear-gradient(135deg,rgba(248,81,73,0.1),rgba(248,81,73,0.02))">
        <h2>Entry Zone ({len(entry_zone)})</h2>
        <p class="section-sub">RSI <= 35 right now + MACD converging -- ACT</p>
    </div>
    <div id="stratEntryCards"></div>

    <div class="section-header" style="margin-top:24px;border-left:4px solid #d29922;background:linear-gradient(135deg,rgba(210,153,34,0.08),rgba(210,153,34,0.02))">
        <h2>Near Zone ({len(near_zone)})</h2>
        <p class="section-sub">RSI 35-42 and MACD converging -- approaching entry, set alerts</p>
    </div>
    <div id="stratNearCards"></div>

    <div class="section-header" style="margin-top:24px;border-left:4px solid #8b949e;background:linear-gradient(135deg,rgba(139,148,158,0.08),rgba(139,148,158,0.02))">
        <h2>Recently Crossed ({len(crossed_zone)})</h2>
        <p class="section-sub">Was in entry zone, MACD has now crossed -- already running, late entry</p>
    </div>
    <div id="stratCrossedCards"></div>
</div>

</div><!-- .container -->

<!-- Detail Panel (shared) -->
<div id="detailPanel" class="detail-panel" style="display:none;">
    <div class="detail-header">
        <h2 id="detailTicker"></h2>
        <button onclick="closeDetail()">&times;</button>
    </div>
    <div id="detailContent"></div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
// DATA (embedded — single source of truth)
// ═══════════════════════════════════════════════════════════════
const ACTION_BRIEF = {brief_json};
const TECH_DATA = {tech_json};
const MF_DATA = {mf_json};
const PLAN_DATA = {plans_json};
const BUY_DATA = {buy_json};
const SELL_DATA = {sell_json};
const ML_DATA = {ml_json};
const STRAT_ENTRY = {strat_entry_json};
const STRAT_NEAR = {strat_near_json};
const STRAT_CROSSED = {strat_crossed_json};
const FII_DII = {fii_json};
const BACKTEST = {bt_json};
const SECTOR_COUNTS = {sector_json};
const FLOW_DATA = {flow_json};

{_get_unified_js()}
</script>

</body>
</html>"""


def _get_unified_css():
    return """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e1e4e8; line-height: 1.5; }
header { background: linear-gradient(135deg, #1a1f2e 0%, #0f1117 100%); border-bottom: 1px solid #2d333b; padding: 20px 32px; }
.header-content { max-width: 1600px; margin: 0 auto; }
header h1 { font-size: 22px; font-weight: 600; color: #f0f3f6; }
.header-top { display: flex; align-items: center; justify-content: space-between; }
.refresh-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; background: #238636; color: #fff; border: 1px solid #2ea043; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.refresh-btn:hover { background: #2ea043; }
.refresh-btn:disabled { background: #1a1f2e; border-color: #2d333b; color: #8b949e; cursor: not-allowed; }
.refresh-btn .refresh-icon { transition: transform 0.3s; }
.refresh-btn.spinning .refresh-icon { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.header-meta { margin-top: 6px; display: flex; gap: 20px; font-size: 13px; color: #8b949e; }
.failed-count { color: #f85149; }

/* Tab Bar */
.tab-bar { display: flex; gap: 0; margin-top: 16px; border-bottom: 2px solid #2d333b; }
.tab { padding: 10px 24px; color: #8b949e; background: none; border: none; font-size: 14px; font-weight: 500; border-bottom: 2px solid transparent; margin-bottom: -2px; cursor: pointer; transition: all 0.15s; }
.tab:hover { color: #f0f3f6; }
.tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }

/* Tab Content */
.container { max-width: 1600px; margin: 0 auto; padding: 20px 32px; }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Summary Cards */
.summary-grid { display: grid; gap: 12px; margin-bottom: 20px; }
.summary-grid.six-col { grid-template-columns: repeat(6, 1fr); }
.summary-grid.four-col { grid-template-columns: repeat(4, 1fr); }
.summary-card { background: #161b22; border: 1px solid #2d333b; border-radius: 8px; padding: 16px; text-align: center; }
.card-value { font-size: 28px; font-weight: 700; }
.card-label { font-size: 12px; color: #8b949e; text-transform: uppercase; margin-top: 4px; }
.summary-card.strong-buy { border-left: 4px solid #2ea043; }
.summary-card.strong-buy .card-value { color: #2ea043; }
.summary-card.buy { border-left: 4px solid #56d364; }
.summary-card.buy .card-value { color: #56d364; }
.summary-card.watch, .summary-card.watch-card { border-left: 4px solid #d29922; }
.summary-card.watch .card-value, .summary-card.watch-card .card-value { color: #d29922; }
.summary-card.hold { border-left: 4px solid #8b949e; }
.summary-card.hold .card-value { color: #8b949e; }
.summary-card.sell { border-left: 4px solid #f0883e; }
.summary-card.sell .card-value { color: #f0883e; }
.summary-card.strong-sell { border-left: 4px solid #f85149; }
.summary-card.strong-sell .card-value { color: #f85149; }
.summary-card.enter-card { border-left: 4px solid #2ea043; }
.summary-card.enter-card .card-value { color: #2ea043; }
.summary-card.avoid-card { border-left: 4px solid #f0883e; }
.summary-card.avoid-card .card-value { color: #f0883e; }
.summary-card.exit-card { border-left: 4px solid #f85149; }
.summary-card.exit-card .card-value { color: #f85149; }

/* Filters */
.filters { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; background: #161b22; border: 1px solid #2d333b; border-radius: 8px; padding: 12px 16px; }
.filter-group { display: flex; align-items: center; gap: 8px; }
.filter-group label { font-size: 13px; color: #8b949e; white-space: nowrap; }
.filter-group select, .filter-group input { background: #0d1117; border: 1px solid #30363d; color: #e1e4e8; padding: 6px 10px; border-radius: 6px; font-size: 13px; }
.filter-group input[type="text"] { width: 120px; }
.filter-group input[type="number"] { width: 90px; }

/* Table */
.table-wrapper { overflow-x: auto; border: 1px solid #2d333b; border-radius: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead { background: #161b22; position: sticky; top: 0; z-index: 10; }
th { padding: 10px 10px; text-align: left; font-weight: 600; color: #8b949e; border-bottom: 2px solid #2d333b; white-space: nowrap; user-select: none; }
th.sortable { cursor: pointer; }
th.sortable:hover { color: #f0f3f6; }
th.sort-asc::after { content: ' \\25B2'; font-size: 10px; }
th.sort-desc::after { content: ' \\25BC'; font-size: 10px; }
td { padding: 8px 10px; border-bottom: 1px solid #21262d; white-space: nowrap; }
tr:hover { background: #1c2128; }
tr.clickable { cursor: pointer; }
.ticker-cell { font-weight: 600; color: #58a6ff; }
.positive { color: #56d364; }
.negative { color: #f85149; }
.neutral-val { color: #8b949e; }
.warn { color: #d29922; }

/* Pills */
.indicator-pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; }
.pill-bullish { background: rgba(86, 211, 100, 0.15); color: #56d364; }
.pill-bearish { background: rgba(248, 81, 73, 0.15); color: #f85149; }
.pill-neutral { background: rgba(139, 148, 158, 0.1); color: #8b949e; }
.pill-warn { background: rgba(210, 153, 34, 0.15); color: #d29922; }
.pill-hot { background: rgba(46, 160, 67, 0.3); color: #2ea043; border: 1px solid #2ea043; }

/* Action badges */
.action-badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; text-transform: uppercase; }
.action-STRONG_BUY { background: rgba(46, 160, 67, 0.2); color: #2ea043; border: 1px solid #2ea043; }
.action-BUY { background: rgba(86, 211, 100, 0.15); color: #56d364; border: 1px solid #56d364; }
.action-WATCH { background: rgba(210, 153, 34, 0.15); color: #d29922; border: 1px solid #d29922; }
.action-HOLD { background: rgba(139, 148, 158, 0.15); color: #8b949e; border: 1px solid #8b949e; }
.action-SELL { background: rgba(240, 136, 62, 0.15); color: #f0883e; border: 1px solid #f0883e; }
.action-STRONG_SELL { background: rgba(248, 81, 73, 0.2); color: #f85149; border: 1px solid #f85149; }
.action-AVOID { background: rgba(240, 136, 62, 0.15); color: #f0883e; border: 1px solid #f0883e; }
.action-ENTER { background: rgba(46, 160, 67, 0.2); color: #2ea043; border: 1px solid #2ea043; }
.action-WAIT { background: rgba(210, 153, 34, 0.15); color: #d29922; border: 1px solid #d29922; }
.action-EXIT { background: rgba(248, 81, 73, 0.2); color: #f85149; border: 1px solid #f85149; }

/* Score bar */
.score-bar { display: flex; align-items: center; gap: 4px; }

/* R:R */
.rr-good { color: #2ea043; font-weight: 700; }
.rr-ok { color: #d29922; font-weight: 600; }
.rr-bad { color: #f85149; }

/* Sector */
.sector-pill { font-size: 11px; color: #8b949e; }
.section-title { font-size: 14px; font-weight: 600; color: #f0f3f6; margin-bottom: 8px; }
.sector-heatmap { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.sector-chip { padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600; background: #161b22; border: 1px solid #2d333b; }
.sector-chip.hot { background: rgba(46,160,67,0.2); color: #2ea043; border-color: #2ea043; }
.sector-chip.warm { background: rgba(210,153,34,0.15); color: #d29922; border-color: #d29922; }
.sector-chip.concentrated { background: rgba(248,81,73,0.15); color: #f85149; border-color: #f85149; }

/* Regime Banner */
.regime-banner { display: flex; align-items: center; gap: 16px; padding: 16px 20px; border-radius: 10px; margin-bottom: 16px; }
.regime-bull { background: linear-gradient(135deg, rgba(46,160,67,0.15), rgba(46,160,67,0.05)); border: 1px solid #2ea043; }
.regime-bear { background: linear-gradient(135deg, rgba(248,81,73,0.15), rgba(248,81,73,0.05)); border: 1px solid #f85149; }
.regime-sideways { background: linear-gradient(135deg, rgba(210,153,34,0.15), rgba(210,153,34,0.05)); border: 1px solid #d29922; }
.regime-icon { font-size: 32px; }
.regime-bull .regime-icon { color: #2ea043; }
.regime-bear .regime-icon { color: #f85149; }
.regime-sideways .regime-icon { color: #d29922; }
.regime-label { font-size: 11px; text-transform: uppercase; color: #8b949e; font-weight: 600; letter-spacing: 1px; }
.regime-desc { font-size: 15px; font-weight: 600; color: #f0f3f6; }
.regime-warning { margin-left: auto; padding: 6px 14px; background: rgba(248,81,73,0.2); color: #f85149; border-radius: 6px; font-size: 12px; font-weight: 600; }

/* Capital Bar */
.capital-bar { display: flex; align-items: center; gap: 20px; padding: 12px 16px; background: #161b22; border: 1px solid #2d333b; border-radius: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.capital-group { display: flex; align-items: center; gap: 8px; }
.capital-group label { font-size: 13px; color: #8b949e; }
.capital-group input, .capital-group select { background: #0d1117; border: 1px solid #30363d; color: #e1e4e8; padding: 6px 10px; border-radius: 6px; font-size: 13px; }
.capital-group input[type="number"] { width: 130px; }
.capital-info { font-size: 13px; color: #58a6ff; font-weight: 600; margin-left: auto; }

/* FII/DII */
.fii-dii-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; margin-bottom: 20px; }
.fii-card { background: #161b22; border: 1px solid #2d333b; border-radius: 8px; padding: 16px; }
.fii-card h3 { font-size: 13px; color: #8b949e; text-transform: uppercase; margin-bottom: 8px; }
.fii-row { display: flex; justify-content: space-between; padding: 3px 0; font-size: 13px; }
.fii-row .label { color: #8b949e; }
.fii-row .value { font-weight: 600; }

/* MFI gauge */
.mfi-gauge { display: flex; align-items: center; gap: 4px; }
.mfi-bar { width: 40px; height: 6px; background: #21262d; border-radius: 3px; overflow: hidden; }
.mfi-fill { height: 100%; border-radius: 3px; }
.flow-cell { font-weight: 600; font-size: 12px; }

/* Opportunity Cards */
.section-header { margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #21262d; }
.section-header h2 { font-size: 18px; font-weight: 700; }
.buy-section h2 { color: #2ea043; }
.sell-section h2 { color: #f85149; }
.sell-section { margin-top: 40px; }
.section-sub { font-size: 13px; color: #8b949e; margin-top: 4px; }

.opp-card { background: #161b22; border: 1px solid #2d333b; border-radius: 10px; padding: 16px 20px; margin-bottom: 12px; cursor: pointer; transition: border-color 0.15s; }
.opp-card:hover { border-color: #58a6ff; }
.opp-card.buy-card { border-left: 4px solid #2ea043; }
.opp-card.sell-card { border-left: 4px solid #f85149; }
.opp-card.ml-card { border-left: 4px solid #1f6feb; }
.cat-badge { padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.cat-confirmed { background: rgba(46,160,67,0.25); color: #3fb950; }
.cat-early { background: rgba(31,111,235,0.25); color: #58a6ff; }
.cat-unconfirmed { background: rgba(210,153,34,0.2); color: #d29922; }
.cat-trap { background: rgba(248,81,73,0.25); color: #f85149; }
.cat-neutral { background: rgba(139,148,158,0.1); color: #8b949e; }
.opp-top { display: flex; align-items: center; gap: 16px; margin-bottom: 10px; flex-wrap: wrap; }
.opp-ticker { font-size: 18px; font-weight: 700; color: #58a6ff; min-width: 120px; }
.opp-ticker .sector { font-size: 11px; color: #6e7681; font-weight: 400; display: block; }
.opp-price { font-size: 15px; font-weight: 600; color: #f0f3f6; min-width: 90px; }
.opp-scores { display: flex; gap: 12px; }
.score-chip { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; }
.score-chip.tech-pos { background: rgba(86,211,100,0.15); color: #56d364; }
.score-chip.tech-neg { background: rgba(248,81,73,0.15); color: #f85149; }
.score-chip.tech-neutral { background: rgba(139,148,158,0.1); color: #8b949e; }
.score-chip.flow-pos { background: rgba(86,211,100,0.1); color: #56d364; border: 1px solid #2ea043; }
.score-chip.flow-neg { background: rgba(248,81,73,0.1); color: #f85149; border: 1px solid #f85149; }
.score-chip.flow-neutral { background: rgba(139,148,158,0.05); color: #8b949e; border: 1px solid #30363d; }
.opp-alignment { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.align-strong { background: rgba(46,160,67,0.2); color: #2ea043; }
.align-partial { background: rgba(210,153,34,0.15); color: #d29922; }
.align-conflict { background: rgba(248,81,73,0.15); color: #f85149; }
.align-neutral { background: rgba(139,148,158,0.1); color: #8b949e; }
.opp-rr { margin-left: auto; text-align: right; }
.opp-rr .rr-val { font-size: 18px; font-weight: 700; }
.rr-label { font-size: 10px; color: #6e7681; text-transform: uppercase; }
.opp-why { font-size: 14px; color: #f0f3f6; font-weight: 500; margin-bottom: 8px; }
.opp-levels { display: flex; gap: 24px; font-size: 12px; color: #8b949e; flex-wrap: wrap; }
.opp-levels span { display: flex; align-items: center; gap: 4px; }
.sl-val { color: #f85149; font-weight: 600; }
.tgt-val { color: #2ea043; font-weight: 600; }
.qty-val { color: #d29922; font-weight: 600; }
.opp-risks { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
.risk-flag { padding: 2px 8px; border-radius: 4px; font-size: 11px; background: rgba(248,81,73,0.1); color: #f0883e; border: 1px solid rgba(240,136,62,0.3); }

/* Detail Panel */
.detail-panel { position: fixed; right: 0; top: 0; width: 440px; height: 100vh; background: #161b22; border-left: 1px solid #2d333b; padding: 24px; overflow-y: auto; z-index: 100; box-shadow: -4px 0 20px rgba(0,0,0,0.4); }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.detail-header h2 { font-size: 20px; color: #58a6ff; }
.detail-header button { background: none; border: none; color: #8b949e; font-size: 24px; cursor: pointer; }
.detail-section { margin-bottom: 16px; padding: 12px; background: #0d1117; border-radius: 8px; border: 1px solid #21262d; }
.detail-section h3 { font-size: 13px; color: #8b949e; text-transform: uppercase; margin-bottom: 8px; }
.detail-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
.detail-row .label { color: #8b949e; }
.detail-row .value { font-weight: 500; }
.reason-list { list-style: none; padding: 0; }
.reason-list li { padding: 4px 0; font-size: 13px; border-bottom: 1px solid #21262d; }
.reason-list li:last-child { border-bottom: none; }

.trade-card { background: linear-gradient(135deg, rgba(46,160,67,0.1), rgba(46,160,67,0.02)); border: 1px solid #2ea043; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
.trade-card.exit-card { background: linear-gradient(135deg, rgba(248,81,73,0.1), rgba(248,81,73,0.02)); border-color: #f85149; }
.trade-card h3 { color: #f0f3f6; margin-bottom: 10px; font-size: 15px; }
.trade-param { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #21262d; }
.trade-param:last-child { border-bottom: none; }
.trade-param .tp-label { color: #8b949e; font-size: 13px; }
.trade-param .tp-value { font-size: 14px; font-weight: 700; }
.tp-entry { color: #58a6ff; }
.tp-sl { color: #f85149; }
.tp-target { color: #2ea043; }
.tp-qty { color: #d29922; }

/* ── Flow Tracker (Tab 5) ─────────────────────────────────── */
.ft-header { padding: 16px 0; border-bottom: 1px solid #2d333b; margin-bottom: 16px; }
.ft-header-row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.ft-stock-select-wrap { position: relative; }
.ft-stock-select { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; color: #f0f3f6; padding: 10px 14px; font-size: 15px; font-weight: 600; cursor: pointer; min-width: 200px; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 4l4 4 4-4' stroke='%238b949e' fill='none' stroke-width='2'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 32px; }
.ft-stock-select:focus { outline: none; border-color: #58a6ff; }
.ft-stock-meta { display: flex; align-items: center; gap: 12px; }
.ft-sector-badge { background: #21262d; color: #8b949e; padding: 4px 12px; border-radius: 12px; font-size: 12px; }
.ft-price-block { margin-left: auto; text-align: right; }
.ft-price { font-size: 22px; font-weight: 600; color: #f0f3f6; }
.ft-change { font-size: 14px; font-weight: 500; }

.ft-toolbar { display: flex; gap: 8px; padding: 12px 16px; background: #161b22; border: 1px solid #2d333b; border-radius: 8px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
.ft-toolbar-label { font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-right: 4px; }
.ft-filter-btn { padding: 7px 18px; border-radius: 8px; border: 1px solid #30363d; background: #161b22; color: #8b949e; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s; }
.ft-filter-btn:hover { border-color: #58a6ff; color: #f0f3f6; }
.ft-filter-btn.active { background: #1c3a5f; border-color: #58a6ff; color: #58a6ff; }
.ft-search-input { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; color: #e1e4e8; padding: 7px 12px; font-size: 12px; width: 180px; margin-left: auto; }
.ft-search-input:focus { outline: none; border-color: #58a6ff; }

.ft-summary-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.ft-summary-card { background: #161b22; border: 1px solid #2d333b; border-radius: 10px; padding: 14px; text-align: center; }
.ft-summary-label { font-size: 10px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.ft-summary-value { font-size: 20px; font-weight: 700; color: #f0f3f6; }
.ft-summary-sub { font-size: 10px; color: #8b949e; margin-top: 3px; }

.ft-content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.ft-full-width { grid-column: 1 / -1; }
.ft-card { background: #161b22; border: 1px solid #2d333b; border-radius: 10px; overflow: hidden; }
.ft-card-header { padding: 12px 16px; border-bottom: 1px solid #2d333b; font-size: 13px; font-weight: 600; color: #f0f3f6; }
.ft-card-body { padding: 16px; }

.ft-context-bar { display: flex; gap: 20px; flex-wrap: wrap; }
.ft-context-item { }
.ft-context-label { font-size: 10px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
.ft-context-value { font-size: 14px; font-weight: 600; margin-top: 2px; }

.ft-rank-table { max-height: 500px; overflow-y: auto; }
.ft-rank-table table { width: 100%; border-collapse: collapse; font-size: 11px; }
.ft-rank-table th { text-align: left; padding: 8px; color: #8b949e; font-weight: 500; text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px; border-bottom: 1px solid #2d333b; position: sticky; top: 0; background: #161b22; }
.ft-rank-table td { padding: 6px 8px; cursor: pointer; border-bottom: 1px solid #21262d; }
.ft-rank-table tr:hover { background: #1c3a5f; }
.ft-rank-table tr.selected { background: #1c3a5f; }

.ft-waterfall { display: flex; flex-direction: column; gap: 10px; }
.ft-wf-row { display: flex; align-items: center; gap: 12px; padding: 10px 12px; background: #0d1117; border-radius: 8px; }
.ft-wf-label { width: 160px; font-size: 12px; color: #8b949e; flex-shrink: 0; }
.ft-wf-bar-wrap { flex: 1; height: 22px; background: #21262d; border-radius: 4px; overflow: hidden; }
.ft-wf-bar { height: 100%; border-radius: 4px; transition: width 0.4s; min-width: 2px; }
.ft-wf-bar.bar-pos { background: linear-gradient(90deg, #2ea043, #56d364); }
.ft-wf-bar.bar-neg { background: linear-gradient(90deg, #da3633, #f85149); }
.ft-wf-value { width: 100px; text-align: right; font-size: 13px; font-weight: 600; flex-shrink: 0; }

.ft-indicator-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.ft-indicator-item { padding: 10px; background: #0d1117; border-radius: 8px; }
.ft-indicator-name { font-size: 10px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 3px; }
.ft-indicator-value { font-size: 15px; font-weight: 600; color: #f0f3f6; }
.ft-indicator-signal { font-size: 11px; margin-top: 3px; }
.ft-pill { display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 500; }
.ft-pill-green { background: rgba(46,160,67,0.15); color: #56d364; }
.ft-pill-red { background: rgba(248,81,73,0.15); color: #f85149; }
.ft-pill-yellow { background: rgba(210,153,34,0.15); color: #d29922; }
.ft-pill-gray { background: rgba(139,148,158,0.1); color: #8b949e; }

.ft-deal-card { padding: 10px 12px; background: #0d1117; border-radius: 8px; margin-bottom: 6px; }
.ft-deal-header { display: flex; justify-content: space-between; align-items: center; }
.ft-deal-client { font-size: 12px; font-weight: 500; color: #f0f3f6; }
.ft-deal-meta { font-size: 11px; color: #8b949e; margin-top: 3px; }

.ft-table-scroll { max-height: 380px; overflow-y: auto; }
.ft-table-scroll::-webkit-scrollbar { width: 6px; }
.ft-table-scroll::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
.ft-table-scroll table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ft-no-data { text-align: center; color: #8b949e; padding: 24px; font-size: 13px; }

/* Vinoth's Strategy Tab */
.vs-header { background: linear-gradient(135deg, #1a1f2e 0%, #0f1117 100%); border: 1px solid #2d333b; border-radius: 12px; padding: 24px; margin-bottom: 24px; }
.vs-title { font-size: 20px; font-weight: 700; color: #f0f3f6; }
.vs-subtitle { font-size: 14px; color: #8b949e; margin-top: 4px; }
.vs-stats-row { display: flex; gap: 24px; margin-top: 16px; flex-wrap: wrap; }
.vs-stat { text-align: center; min-width: 100px; }
.vs-stat-val { font-size: 24px; font-weight: 700; }
.vs-stat-label { font-size: 11px; color: #6e7681; text-transform: uppercase; letter-spacing: 0.5px; }
.vs-green { color: #3fb950; }
.vs-blue { color: #58a6ff; }
.vs-yellow { color: #d29922; }
.vs-rule { margin-top: 16px; padding: 10px 16px; background: rgba(31,111,235,0.08); border: 1px solid rgba(31,111,235,0.2); border-radius: 8px; font-size: 13px; color: #8b949e; }
.vs-card { background: #161b22; border: 1px solid #2d333b; border-radius: 10px; padding: 16px 20px; margin-bottom: 12px; transition: border-color 0.15s; }
.vs-card:hover { border-color: #58a6ff; }
.vs-card.zone-entry { border-left: 4px solid #f85149; }
.vs-card.zone-near { border-left: 4px solid #d29922; }
.vs-card.zone-crossed { border-left: 4px solid #8b949e; }
.vs-card-top { display: flex; align-items: center; gap: 16px; margin-bottom: 8px; flex-wrap: wrap; }
.vs-card-ticker { font-size: 18px; font-weight: 700; color: #58a6ff; min-width: 120px; }
.vs-card-ticker .sector { font-size: 11px; color: #6e7681; font-weight: 400; display: block; }
.vs-card-price { font-size: 15px; font-weight: 600; color: #f0f3f6; }
.vs-zone-badge { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.vs-zone-entry { background: rgba(248,81,73,0.2); color: #f85149; }
.vs-zone-near { background: rgba(210,153,34,0.15); color: #d29922; }
.vs-zone-crossed { background: rgba(139,148,158,0.15); color: #8b949e; }
.vs-indicators { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; }
.vs-ind { display: flex; flex-direction: column; align-items: center; min-width: 80px; }
.vs-ind-val { font-size: 16px; font-weight: 700; }
.vs-ind-label { font-size: 10px; color: #6e7681; text-transform: uppercase; }
.vs-card-label { font-size: 13px; color: #f0f3f6; margin-bottom: 6px; }
.vs-card-levels { display: flex; gap: 24px; font-size: 12px; color: #8b949e; flex-wrap: wrap; }
.vs-card-levels span { display: flex; align-items: center; gap: 4px; }
.vs-hist-bar { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.vs-hist-track { width: 80px; height: 6px; background: #21262d; border-radius: 3px; overflow: hidden; position: relative; }
.vs-hist-fill { height: 100%; border-radius: 3px; }
.vs-hist-label { font-size: 11px; color: #8b949e; }
.vs-backtest { display: flex; gap: 12px; margin-top: 8px; font-size: 12px; }
.vs-bt-chip { padding: 3px 8px; border-radius: 4px; background: rgba(86,211,100,0.1); color: #56d364; font-weight: 600; }
.vs-bt-chip.warn { background: rgba(248,81,73,0.1); color: #f85149; }
.vs-risks { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.vs-risk-flag { font-size: 11px; padding: 3px 8px; border-radius: 4px; background: rgba(240,136,62,0.1); color: #f0883e; }
.vs-no-data { padding: 20px; color: #8b949e; text-align: center; font-size: 14px; }

/* ── Action Brief ─────────────────────────────────── */
.ab-stance-banner { padding: 24px 28px; border-radius: 10px; margin-bottom: 24px; }
.ab-stance-banner.red { background: linear-gradient(135deg, rgba(248,81,73,0.15) 0%, rgba(248,81,73,0.05) 100%); border: 1px solid rgba(248,81,73,0.3); }
.ab-stance-banner.amber { background: linear-gradient(135deg, rgba(240,183,62,0.15) 0%, rgba(240,183,62,0.05) 100%); border: 1px solid rgba(240,183,62,0.3); }
.ab-stance-banner.green { background: linear-gradient(135deg, rgba(63,185,80,0.15) 0%, rgba(63,185,80,0.05) 100%); border: 1px solid rgba(63,185,80,0.3); }
.ab-stance-title { font-size: 28px; font-weight: 700; margin-bottom: 6px; }
.ab-stance-banner.red .ab-stance-title { color: #f85149; }
.ab-stance-banner.amber .ab-stance-title { color: #f0b73e; }
.ab-stance-banner.green .ab-stance-title { color: #3fb950; }
.ab-stance-meta { display: flex; gap: 24px; flex-wrap: wrap; font-size: 13px; color: #8b949e; margin-bottom: 10px; }
.ab-stance-meta .ab-meta-item { display: flex; align-items: center; gap: 6px; }
.ab-stance-meta .fii-neg { color: #f85149; }
.ab-stance-meta .fii-pos { color: #3fb950; }
.ab-stance-meta .dii-neg { color: #f85149; }
.ab-stance-meta .dii-pos { color: #3fb950; }
.ab-rationale { font-size: 14px; color: #c9d1d9; line-height: 1.6; }
.ab-section { margin-bottom: 28px; }
.ab-section-title { font-size: 16px; font-weight: 600; color: #f0f3f6; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid #21262d; display: flex; align-items: center; gap: 8px; }
.ab-section-count { font-size: 12px; font-weight: 500; color: #8b949e; background: #21262d; padding: 2px 8px; border-radius: 10px; }
.ab-empty { padding: 16px; color: #8b949e; font-size: 13px; font-style: italic; }
.ab-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.ab-card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 16px; transition: border-color 0.15s; }
.ab-card:hover { border-color: #388bfd; }
.ab-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.ab-ticker { font-size: 16px; font-weight: 700; color: #f0f3f6; }
.ab-sector { font-size: 11px; color: #8b949e; }
.ab-action-badge { font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
.ab-action-badge.buy-now { background: rgba(63,185,80,0.2); color: #3fb950; }
.ab-action-badge.exit { background: rgba(248,81,73,0.2); color: #f85149; }
.ab-action-badge.trail-stop { background: rgba(136,132,216,0.2); color: #a5a0f0; }
.ab-card-levels { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
.ab-level { text-align: center; }
.ab-level-label { font-size: 10px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
.ab-level-value { font-size: 14px; font-weight: 600; color: #c9d1d9; }
.ab-level-value.sl { color: #f85149; }
.ab-level-value.target { color: #3fb950; }
.ab-level-value.rr { color: #f0b73e; }
.ab-reason { font-size: 12px; color: #8b949e; line-height: 1.5; border-top: 1px solid #21262d; padding-top: 8px; }
/* Watchlist */
.ab-watch-table { width: 100%; border-collapse: collapse; }
.ab-watch-table th { text-align: left; font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; padding: 8px 12px; border-bottom: 1px solid #21262d; }
.ab-watch-table td { padding: 10px 12px; border-bottom: 1px solid #161b22; font-size: 13px; color: #c9d1d9; }
.ab-watch-table tr:hover td { background: #161b22; }
.ab-watch-ticker { font-weight: 700; color: #f0f3f6; }
.ab-watch-trigger { color: #8b949e; font-size: 12px; max-width: 350px; }
/* Conflicts */
.ab-conflict { background: #161b22; border-left: 3px solid #f0b73e; padding: 12px 16px; margin-bottom: 10px; border-radius: 0 6px 6px 0; font-size: 13px; color: #c9d1d9; line-height: 1.6; }
.ab-signal-bar { display: flex; gap: 16px; margin-top: 8px; flex-wrap: wrap; }
.ab-signal-item { font-size: 12px; padding: 4px 10px; border-radius: 4px; background: #21262d; color: #8b949e; }
.ab-signal-item.positive { background: rgba(63,185,80,0.1); color: #3fb950; }
.ab-signal-item.negative { background: rgba(248,81,73,0.1); color: #f85149; }
.ab-signal-item.neutral { background: rgba(136,132,216,0.1); color: #a5a0f0; }

@media (max-width: 1200px) { .summary-grid.six-col { grid-template-columns: repeat(3, 1fr); } .container { padding: 16px; } .ft-content-grid { grid-template-columns: 1fr; } .ab-cards { grid-template-columns: 1fr; } }
@media (max-width: 768px) { .summary-grid.six-col { grid-template-columns: repeat(2, 1fr); } .summary-grid.four-col { grid-template-columns: repeat(2, 1fr); } .detail-panel { width: 100%; } .opp-top { flex-wrap: wrap; } .ft-summary-row { grid-template-columns: repeat(2, 1fr); } .ab-cards { grid-template-columns: 1fr; } }
"""


def _get_unified_js():
    return """
// ═══════════════════════════════════════════════════════════════
// REFRESH
// ═══════════════════════════════════════════════════════════════
function refreshDashboard() {
    const btn = document.getElementById('refreshBtn');
    const label = document.getElementById('refreshLabel');
    btn.disabled = true;
    btn.classList.add('spinning');
    label.textContent = 'Refreshing...';

    fetch('/refresh', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'already_running') {
                label.textContent = 'Already running...';
            }
            // Poll for completion
            const poll = setInterval(() => {
                fetch('/refresh/status')
                    .then(r => r.json())
                    .then(s => {
                        if (!s.refreshing) {
                            clearInterval(poll);
                            window.location.reload();
                        }
                    })
                    .catch(() => clearInterval(poll));
            }, 3000);
        })
        .catch(() => {
            label.textContent = 'Refresh (open via serve mode)';
            btn.disabled = false;
            btn.classList.remove('spinning');
        });
}

// ═══════════════════════════════════════════════════════════════
// TAB SWITCHING
// ═══════════════════════════════════════════════════════════════
document.querySelectorAll('.tab-bar .tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-bar .tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    });
});

// ═══════════════════════════════════════════════════════════════
// TAB 0: ACTION BRIEF
// ═══════════════════════════════════════════════════════════════
function renderActionBrief(brief) {
    const el = document.getElementById('actionBriefContent');
    if (!brief || !brief.stance) { el.innerHTML = '<div class="ab-empty">No data available</div>'; return; }

    const fiiCls = brief.fii_net >= 0 ? 'fii-pos' : 'fii-neg';
    const diiCls = brief.dii_net >= 0 ? 'dii-pos' : 'dii-neg';
    const fmtCr = v => (v >= 0 ? '+' : '') + v.toLocaleString('en-IN', {maximumFractionDigits:0});

    // Stance banner
    let html = `
    <div class="ab-stance-banner ${brief.stance_color}">
        <div class="ab-stance-title">${brief.stance}</div>
        <div class="ab-stance-meta">
            <span class="ab-meta-item">Regime: <strong>${brief.regime.toUpperCase()}</strong></span>
            <span class="ab-meta-item">FII: <strong class="${fiiCls}">${fmtCr(brief.fii_net)} Cr</strong></span>
            <span class="ab-meta-item">DII: <strong class="${diiCls}">${fmtCr(brief.dii_net)} Cr</strong></span>
            <span class="ab-meta-item">Bullish: <strong>${brief.bullish_pct}%</strong> of stocks</span>
        </div>
        <div class="ab-rationale">${brief.rationale}</div>
        <div class="ab-signal-bar">
            <span class="ab-signal-item ${brief.enter_count > 0 ? 'positive' : 'negative'}">ENTER: ${brief.enter_count}</span>
            <span class="ab-signal-item ${brief.wait_count > 0 ? 'neutral' : ''}">${brief.wait_count > 0 ? 'WAIT: '+brief.wait_count : 'WAIT: 0'}</span>
            <span class="ab-signal-item negative">AVOID: ${brief.avoid_count}</span>
            <span class="ab-signal-item ${brief.exit_count > 0 ? 'negative' : ''}">EXIT: ${brief.exit_count}</span>
            <span class="ab-signal-item ${brief.entry_zone_count > 0 ? 'neutral' : ''}">Strategy Entry: ${brief.entry_zone_count}</span>
        </div>
    </div>`;

    // Action items
    html += `<div class="ab-section">
        <div class="ab-section-title">Action Items <span class="ab-section-count">${brief.actions.length}</span></div>`;
    if (brief.actions.length === 0) {
        html += `<div class="ab-empty">No actions required today. The best trade is no trade.</div>`;
    } else {
        html += `<div class="ab-cards">`;
        for (const a of brief.actions) {
            const badgeCls = a.type === 'BUY NOW' ? 'buy-now' : a.type === 'EXIT' ? 'exit' : 'trail-stop';
            const showLevels = a.type !== 'EXIT';
            html += `
            <div class="ab-card">
                <div class="ab-card-header">
                    <div><span class="ab-ticker">${a.ticker}</span> <span class="ab-sector">${a.sector || ''}</span></div>
                    <span class="ab-action-badge ${badgeCls}">${a.type}</span>
                </div>
                <div style="font-size:14px;color:#c9d1d9;margin-bottom:10px">CMP: <strong>₹${a.price ? a.price.toLocaleString('en-IN') : '-'}</strong></div>
                ${showLevels ? `<div class="ab-card-levels">
                    <div class="ab-level"><div class="ab-level-label">Stop Loss</div><div class="ab-level-value sl">₹${a.stop_loss ? a.stop_loss.toLocaleString('en-IN') : '-'} ${a.sl_pct ? '('+a.sl_pct.toFixed(1)+'%)' : ''}</div></div>
                    <div class="ab-level"><div class="ab-level-label">Target</div><div class="ab-level-value target">₹${a.target ? a.target.toLocaleString('en-IN') : '-'} ${a.target_pct ? '(+'+a.target_pct.toFixed(1)+'%)' : ''}</div></div>
                    <div class="ab-level"><div class="ab-level-label">R:R</div><div class="ab-level-value rr">${a.risk_reward ? a.risk_reward.toFixed(1)+'x' : '-'}</div></div>
                </div>` : ''}
                <div class="ab-reason">${a.reason}</div>
            </div>`;
        }
        html += `</div>`;
    }
    html += `</div>`;

    // Watchlist
    html += `<div class="ab-section">
        <div class="ab-section-title">Watchlist — First to Flip <span class="ab-section-count">${brief.watchlist.length}</span></div>`;
    if (brief.watchlist.length === 0) {
        html += `<div class="ab-empty">No stocks near actionable levels.</div>`;
    } else {
        html += `<table class="ab-watch-table"><thead><tr>
            <th>Stock</th><th>Sector</th><th>CMP</th><th>Score</th><th>Upside</th><th>R:R</th><th>What's Needed</th>
        </tr></thead><tbody>`;
        for (const w of brief.watchlist) {
            html += `<tr>
                <td class="ab-watch-ticker">${w.ticker}</td>
                <td>${w.sector || '-'}</td>
                <td>₹${w.price ? w.price.toLocaleString('en-IN') : '-'}</td>
                <td>${w.combined_score !== null ? w.combined_score.toFixed(1) : '-'}</td>
                <td>${w.target_pct !== null ? '+'+w.target_pct.toFixed(1)+'%' : '-'}</td>
                <td>${w.risk_reward !== null ? w.risk_reward.toFixed(1)+'x' : '-'}</td>
                <td class="ab-watch-trigger">${w.trigger}</td>
            </tr>`;
        }
        html += `</tbody></table>`;
    }
    html += `</div>`;

    // Conflicts
    if (brief.conflicts && brief.conflicts.length > 0) {
        html += `<div class="ab-section">
            <div class="ab-section-title">Why Other Tabs Disagree <span class="ab-section-count">${brief.conflicts.length}</span></div>`;
        for (const c of brief.conflicts) {
            html += `<div class="ab-conflict">${c}</div>`;
        }
        html += `</div>`;
    }

    el.innerHTML = html;
}

// ═══════════════════════════════════════════════════════════════
// SHARED UTILITIES
// ═══════════════════════════════════════════════════════════════
function fmt(v, dec=2) { if (v === null || v === undefined) return '-'; return Number(v).toFixed(dec); }
function fmtPct(v) { if (v === null || v === undefined) return '-'; return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; }
function fmtPct0(v) { if (v === null || v === undefined) return '-'; return (v >= 0 ? '+' : '') + v.toFixed(0) + '%'; }
function changeClass(v) { if (v === null || v === undefined) return 'neutral-val'; return v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral-val'; }
function volClass(v) { if (v === null) return 'neutral-val'; if (v >= 2.0) return 'warn'; if (v >= 1.5) return 'positive'; return ''; }
function rrClass(v) { if (v === null) return 'neutral-val'; if (v >= 2.0) return 'rr-good'; if (v >= 1.0) return 'rr-ok'; return 'rr-bad'; }

function actionBadge(action) {
    const cls = action.replace(/ /g, '_');
    return `<span class="action-badge action-${cls}">${action}</span>`;
}

function pill(text, cls) { return `<span class="indicator-pill ${cls}">${text}</span>`; }

function macdPill(sig) {
    const m = {'bullish_crossover':['CROSS UP','pill-hot'],'bearish_crossover':['CROSS DN','pill-bearish'],'bullish':['Bullish','pill-bullish'],'bearish':['Bearish','pill-bearish'],'neutral':['Neutral','pill-neutral']};
    const [t,c] = m[sig]||['?','pill-neutral']; return pill(t,c);
}
function bbPill(sig) {
    const m = {'squeeze':['SQUEEZE','pill-warn'],'lower_band_touch':['Lower','pill-bullish'],'upper_band_touch':['Upper','pill-bearish'],'walking_upper':['Walk Up','pill-hot'],'walking_lower':['Walk Dn','pill-bearish'],'mid_band':['Mid','pill-neutral'],'neutral':['Neutral','pill-neutral']};
    const [t,c] = m[sig]||['?','pill-neutral']; return pill(t,c);
}
function emaPill(sig) {
    const m = {'bullish_crossover':['CROSS UP','pill-hot'],'bearish_crossover':['CROSS DN','pill-bearish'],'bullish':['Bullish','pill-bullish'],'bearish':['Bearish','pill-bearish'],'neutral':['Neutral','pill-neutral']};
    const [t,c] = m[sig]||['?','pill-neutral']; return pill(t,c);
}
function vwapPill(sig) {
    const m = {'vwap_reclaim':['RECLAIM','pill-hot'],'above_vwap':['Above','pill-bullish'],'below_vwap':['Below','pill-bearish'],'neutral':['Neutral','pill-neutral']};
    const [t,c] = m[sig]||['?','pill-neutral']; return pill(t,c);
}
function rsPill(sig) {
    const m = {'rs_new_high':['NEW HIGH','pill-hot'],'rs_improving':['Improving','pill-bullish'],'rs_declining':['Declining','pill-bearish'],'rs_new_low':['New Low','pill-bearish'],'neutral':['Neutral','pill-neutral']};
    const [t,c] = m[sig]||['?','pill-neutral']; return pill(t,c);
}
function trendPill(t) {
    const m = {'strong_uptrend':['Strong Up','pill-hot'],'uptrend':['Up','pill-bullish'],'downtrend':['Down','pill-bearish'],'strong_downtrend':['Strong Dn','pill-bearish'],'sideways':['Sideways','pill-neutral']};
    const [tx,c] = m[t]||['?','pill-neutral']; return pill(tx,c);
}
function obvPill(t) {
    const m = {'rising':['Rising','pill-bullish'],'falling':['Falling','pill-bearish'],'flat':['Flat','pill-neutral']};
    const [tx,c] = m[t]||['?','pill-neutral']; return pill(tx,c);
}
function divPill(d) {
    if (d==='bullish_div') return pill('Bull Div','pill-hot');
    if (d==='bearish_div') return pill('Bear Div','pill-bearish');
    return pill('None','pill-neutral');
}
function accumPill(s) {
    if (s==='accumulating') return pill('Accumulating','pill-hot');
    if (s==='distributing') return pill('Distributing','pill-bearish');
    return pill('-','pill-neutral');
}
function mfiGauge(mfi, sig) {
    if (mfi===null) return '-';
    let color='#8b949e';
    if (sig==='strong_inflow') color='#2ea043';
    else if (sig==='inflow') color='#56d364';
    else if (sig==='strong_outflow') color='#f85149';
    else if (sig==='outflow') color='#f0883e';
    return `<div class="mfi-gauge"><span style="color:${color};font-weight:600;min-width:24px">${mfi.toFixed(0)}</span><div class="mfi-bar"><div class="mfi-fill" style="width:${mfi}%;background:${color}"></div></div></div>`;
}

function scoreBar16(score) {
    const pct = Math.abs(score)/16*100;
    let color;
    if (score>=7) color='#2ea043'; else if (score>=4) color='#56d364'; else if (score>=1) color='#d29922';
    else if (score<=-5) color='#f85149'; else if (score<=-2) color='#f0883e'; else color='#8b949e';
    return `<div class="score-bar"><span style="color:${color};font-weight:700;min-width:28px">${score>=0?'+':''}${score}</span><div style="width:60px;height:6px;background:#21262d;border-radius:3px;overflow:hidden"><div style="width:${pct}%;height:100%;background:${color};border-radius:3px"></div></div></div>`;
}
function scoreBar10(score) {
    const pct = Math.abs(score)/10*100;
    let color;
    if (score>=5) color='#2ea043'; else if (score>=2) color='#56d364';
    else if (score<=-4) color='#f85149'; else if (score<=-1) color='#f0883e'; else color='#8b949e';
    return `<div class="score-bar"><span style="color:${color};font-weight:700;min-width:28px">${score>=0?'+':''}${score}</span><div style="width:60px;height:6px;background:#21262d;border-radius:3px;overflow:hidden"><div style="width:${pct}%;height:100%;background:${color};border-radius:3px"></div></div></div>`;
}
function scoreBar100(score) {
    const pct = Math.min(Math.abs(score),100);
    let color;
    if (score>=40) color='#2ea043'; else if (score>=20) color='#56d364'; else if (score>=0) color='#8b949e';
    else if (score>=-20) color='#f0883e'; else color='#f85149';
    return `<div class="score-bar"><span style="color:${color};font-weight:700;min-width:36px;font-size:12px">${score>=0?'+':''}${score.toFixed(0)}</span><div style="width:50px;height:5px;background:#21262d;border-radius:3px;overflow:hidden"><div style="width:${pct}%;height:100%;background:${color};border-radius:3px"></div></div></div>`;
}

function sortArray(data, col, dir) {
    data.sort((a,b) => {
        let va=a[col], vb=b[col];
        if (va===null||va===undefined) va = dir==='asc' ? Infinity : -Infinity;
        if (vb===null||vb===undefined) vb = dir==='asc' ? Infinity : -Infinity;
        if (typeof va==='string') return dir==='asc' ? va.localeCompare(vb) : vb.localeCompare(va);
        return dir==='asc' ? va-vb : vb-va;
    });
}

// ═══════════════════════════════════════════════════════════════
// TAB 1: TECHNICAL SIGNALS
// ═══════════════════════════════════════════════════════════════
let techSort = {col:'score', dir:'desc'};

function renderTech(data) {
    sortArray(data, techSort.col, techSort.dir);
    const tbody = document.getElementById('techBody');
    tbody.innerHTML = data.map(s => `<tr class="clickable" onclick='showTechDetail(${JSON.stringify(s).replace(/'/g,"&#39;")})'>
        <td class="ticker-cell">${s.ticker}</td>
        <td>${fmt(s.close)}</td>
        <td class="${changeClass(s.change_1d)}">${fmtPct(s.change_1d)}</td>
        <td class="${changeClass(s.change_5d)}">${fmtPct(s.change_5d)}</td>
        <td class="${changeClass(s.change_20d)}">${fmtPct(s.change_20d)}</td>
        <td class="${s.rsi&&s.rsi<=30?'positive':s.rsi&&s.rsi>=70?'negative':''}">${fmt(s.rsi,0)}</td>
        <td>${macdPill(s.macd_signal)}</td>
        <td>${bbPill(s.bb_signal)}</td>
        <td class="${volClass(s.volume_ratio)}">${fmt(s.volume_ratio,1)}x</td>
        <td>${emaPill(s.ema_cross_signal)}</td>
        <td>${vwapPill(s.vwap_signal)}</td>
        <td>${rsPill(s.rs_signal)}</td>
        <td>${trendPill(s.trend)}</td>
        <td>${scoreBar16(s.score)}</td>
        <td>${actionBadge(s.action)}</td>
    </tr>`).join('');
}

function filterTech() {
    const action = document.getElementById('tech-actionFilter').value;
    const search = document.getElementById('tech-search').value.toUpperCase();
    const min = document.getElementById('tech-minScore').value;
    let d = TECH_DATA.filter(s => {
        if (action!=='all' && s.action!==action) return false;
        if (search && !s.ticker.includes(search)) return false;
        if (min!=='' && s.score < parseInt(min)) return false;
        return true;
    });
    renderTech(d);
}

function showTechDetail(s) {
    document.getElementById('detailPanel').style.display='block';
    document.getElementById('detailTicker').textContent = s.ticker + ' — ' + s.action;
    const reasons = s.reasons.map(r=>`<li>${r}</li>`).join('');
    document.getElementById('detailContent').innerHTML = `
        <div class="detail-section"><h3>Score: ${s.score>=0?'+':''}${s.score} / 16</h3><ul class="reason-list">${reasons||'<li>No signals</li>'}</ul></div>
        <div class="detail-section"><h3>Price</h3>
            <div class="detail-row"><span class="label">Close</span><span class="value">${fmt(s.close)}</span></div>
            <div class="detail-row"><span class="label">1D / 5D / 20D</span><span class="value">${fmtPct(s.change_1d)} / ${fmtPct(s.change_5d)} / ${fmtPct(s.change_20d)}</span></div>
        </div>
        <div class="detail-section"><h3>Momentum</h3>
            <div class="detail-row"><span class="label">RSI</span><span class="value">${fmt(s.rsi,1)}</span></div>
            <div class="detail-row"><span class="label">StochRSI K/D</span><span class="value">${fmt(s.stochrsi_k,1)} / ${fmt(s.stochrsi_d,1)}</span></div>
            <div class="detail-row"><span class="label">MACD Hist</span><span class="value">${fmt(s.macd_histogram,2)}</span></div>
        </div>
        <div class="detail-section"><h3>Trend</h3>
            <div class="detail-row"><span class="label">EMA 20/50</span><span class="value">${emaPill(s.ema_cross_signal)}</span></div>
            <div class="detail-row"><span class="label">VWAP</span><span class="value">${vwapPill(s.vwap_signal)}</span></div>
            <div class="detail-row"><span class="label">RS vs Nifty</span><span class="value">${rsPill(s.rs_signal)}</span></div>
            <div class="detail-row"><span class="label">MA Trend</span><span class="value">${trendPill(s.trend)}</span></div>
            <div class="detail-row"><span class="label">SMA 20/50/200</span><span class="value">${fmt(s.sma_20)} / ${fmt(s.sma_50)} / ${fmt(s.sma_200)}</span></div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// TAB 2: MONEY FLOW
// ═══════════════════════════════════════════════════════════════
let mfSort = {col:'money_flow_score', dir:'desc'};

function renderFiiDii() {
    const section = document.getElementById('fiiDiiSection');
    if (!FII_DII || FII_DII.length===0) { section.innerHTML='<div class="fii-card"><p style="color:#8b949e;font-size:13px">FII/DII data unavailable</p></div>'; return; }
    const groups = {};
    FII_DII.forEach(f => { if (!groups[f.category]) groups[f.category]=[]; groups[f.category].push(f); });
    let html='';
    for (const [cat,entries] of Object.entries(groups)) {
        const l=entries[0]; const nc=l.net>=0?'positive':'negative';
        html+=`<div class="fii-card"><h3>${cat}</h3><div class="fii-row"><span class="label">Date</span><span class="value">${l.date}</span></div><div class="fii-row"><span class="label">Net</span><span class="value ${nc}">${l.net>=0?'+':''}${(l.net/100).toFixed(0)} Cr</span></div></div>`;
    }
    section.innerHTML=html;
}

function renderMF(data) {
    sortArray(data, mfSort.col, mfSort.dir);
    const tbody = document.getElementById('mfBody');
    tbody.innerHTML = data.map(s => `<tr class="clickable" onclick='showMFDetail(${JSON.stringify(s).replace(/'/g,"&#39;")})'>
        <td class="ticker-cell">${s.ticker}</td>
        <td>${fmt(s.close)}</td>
        <td class="${changeClass(s.change_1d)}">${fmtPct(s.change_1d)}</td>
        <td>${mfiGauge(s.mfi, s.mfi_signal)}</td>
        <td class="${s.cmf_signal.includes('accumulation')?'positive':s.cmf_signal.includes('distribution')?'negative':'neutral-val'}">${s.cmf!==null?(s.cmf>=0?'+':'')+s.cmf.toFixed(2):'-'}</td>
        <td>${obvPill(s.obv_trend)}</td>
        <td>${divPill(s.obv_divergence)}</td>
        <td class="${volClass(s.vol_ratio)}">${fmt(s.vol_ratio,1)}x</td>
        <td class="${changeClass(s.vol_trend_5d)}">${fmtPct0(s.vol_trend_5d)}</td>
        <td>${accumPill(s.accumulation_signal)}</td>
        <td>${scoreBar10(s.money_flow_score)}</td>
        <td>${actionBadge(s.action)}</td>
    </tr>`).join('');
}

function filterMF() {
    const flow = document.getElementById('mf-flowFilter').value;
    const search = document.getElementById('mf-search').value.toUpperCase();
    const min = document.getElementById('mf-minScore').value;
    let d = MF_DATA.filter(s => {
        if (flow!=='all' && s.action!==flow) return false;
        if (search && !s.ticker.includes(search)) return false;
        if (min!=='' && s.money_flow_score < parseInt(min)) return false;
        return true;
    });
    renderMF(d);
}

function showMFDetail(s) {
    document.getElementById('detailPanel').style.display='block';
    document.getElementById('detailTicker').textContent = s.ticker + ' — ' + s.action;
    const reasons = s.reasons.map(r=>`<li>${r}</li>`).join('');
    document.getElementById('detailContent').innerHTML = `
        <div class="detail-section"><h3>Score: ${s.money_flow_score>=0?'+':''}${s.money_flow_score} / 10</h3><ul class="reason-list">${reasons||'<li>No signals</li>'}</ul></div>
        <div class="detail-section"><h3>Flow Indicators</h3>
            <div class="detail-row"><span class="label">MFI (14)</span><span class="value">${mfiGauge(s.mfi,s.mfi_signal)}</span></div>
            <div class="detail-row"><span class="label">CMF (20)</span><span class="value">${s.cmf!==null?(s.cmf>=0?'+':'')+s.cmf.toFixed(2):'-'}</span></div>
            <div class="detail-row"><span class="label">OBV</span><span class="value">${obvPill(s.obv_trend)}</span></div>
            <div class="detail-row"><span class="label">Divergence</span><span class="value">${divPill(s.obv_divergence)}</span></div>
            <div class="detail-row"><span class="label">Pattern</span><span class="value">${accumPill(s.accumulation_signal)}</span></div>
        </div>
        <div class="detail-section"><h3>Volume</h3>
            <div class="detail-row"><span class="label">Vol Ratio</span><span class="value">${fmt(s.vol_ratio,1)}x</span></div>
            <div class="detail-row"><span class="label">5D Change</span><span class="value ${changeClass(s.vol_trend_5d)}">${fmtPct0(s.vol_trend_5d)}</span></div>
            <div class="detail-row"><span class="label">20D Change</span><span class="value ${changeClass(s.vol_trend_20d)}">${fmtPct0(s.vol_trend_20d)}</span></div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// TAB 3: TRADE PLANNER
// ═══════════════════════════════════════════════════════════════
let tpSort = {col:'combined_score', dir:'desc'};
let capital = 1000000, riskPct = 1.0;

function updateCapital() {
    capital = parseFloat(document.getElementById('capitalInput').value)||1000000;
    riskPct = parseFloat(document.getElementById('riskPct').value)||1.0;
    const mr = capital*riskPct/100;
    document.getElementById('maxRiskDisplay').textContent = '\\u20B9'+mr.toLocaleString('en-IN');
}

function renderSectorHeatmap() {
    const div = document.getElementById('sectorHeatmap');
    const entries = Object.entries(SECTOR_COUNTS).sort((a,b)=>b[1]-a[1]);
    if (!entries.length) { div.innerHTML='<span style="color:#8b949e;font-size:13px">No ENTER signals</span>'; return; }
    div.innerHTML = entries.map(([s,c]) => {
        let cls='sector-chip'; if (c>=4) cls+=' concentrated'; else if (c>=2) cls+=' warm'; else cls+=' hot';
        return `<div class="${cls}">${s}: ${c}${c>=4?' \\u26A0':''}</div>`;
    }).join('');
}

function populateSectorFilter() {
    const sectors = [...new Set(PLAN_DATA.map(s=>s.sector))].sort();
    const sel = document.getElementById('tp-sectorFilter');
    sectors.forEach(s => { const o=document.createElement('option'); o.value=s; o.textContent=s; sel.appendChild(o); });
}

function getTPFiltered() {
    const action = document.getElementById('tp-actionFilter').value;
    const search = document.getElementById('tp-search').value.toUpperCase();
    const sector = document.getElementById('tp-sectorFilter').value;
    const minRR = parseFloat(document.getElementById('tp-minRR').value)||0;
    return PLAN_DATA.filter(s => {
        if (action!=='all' && s.action!==action) return false;
        if (search && !s.ticker.includes(search)) return false;
        if (sector!=='all' && s.sector!==sector) return false;
        if (minRR>0 && action==='ENTER') { if (s.risk_reward===null||s.risk_reward<minRR) return false; }
        return true;
    });
}

function renderTP(data) {
    sortArray(data, tpSort.col, tpSort.dir);
    const maxRisk = capital*riskPct/100;
    const tbody = document.getElementById('planBody');
    tbody.innerHTML = data.map(s => {
        let qty='-', riskAmt='-';
        if (s.risk_per_share&&s.risk_per_share>0) { const sh=Math.floor(maxRisk/s.risk_per_share); if(sh>0){qty=sh; riskAmt='\\u20B9'+Math.round(sh*s.risk_per_share).toLocaleString('en-IN');} }
        return `<tr class="clickable" onclick='showTPDetail(${JSON.stringify(s).replace(/'/g,"&#39;")})'>
            <td class="ticker-cell">${s.ticker}</td>
            <td class="sector-pill">${s.sector}</td>
            <td>${fmt(s.close)}</td>
            <td>${scoreBar100(s.combined_score)}</td>
            <td class="${s.technical_score>0?'positive':s.technical_score<0?'negative':'neutral-val'}">${s.technical_score>=0?'+':''}${s.technical_score}</td>
            <td class="${s.money_flow_score>0?'positive':s.money_flow_score<0?'negative':'neutral-val'}">${s.money_flow_score>=0?'+':''}${s.money_flow_score}</td>
            <td class="negative">${fmt(s.stop_loss)} <span style="font-size:10px;color:#8b949e">(${fmt(s.sl_pct,1)}%)</span></td>
            <td class="positive">${fmt(s.target)} <span style="font-size:10px;color:#8b949e">(+${fmt(s.target_pct,1)}%)</span></td>
            <td class="${rrClass(s.risk_reward)}">${s.risk_reward!==null?s.risk_reward.toFixed(1)+':1':'-'}</td>
            <td class="tp-qty">${qty}</td>
            <td style="font-size:12px">${riskAmt}</td>
            <td class="${s.dist_from_52w_high!==null&&s.dist_from_52w_high>-5?'warn':'neutral-val'}">${s.dist_from_52w_high!==null?s.dist_from_52w_high.toFixed(0)+'%':'-'}</td>
            <td>${actionBadge(s.action)}</td>
        </tr>`;
    }).join('');
}

function showTPDetail(s) {
    document.getElementById('detailPanel').style.display='block';
    document.getElementById('detailTicker').textContent = s.ticker + ' — ' + s.action;
    const maxRisk=capital*riskPct/100;
    let qty='-',investAmt='-',riskAmt='-';
    if(s.risk_per_share&&s.risk_per_share>0&&s.close){const sh=Math.floor(maxRisk/s.risk_per_share);if(sh>0){qty=sh;investAmt='\\u20B9'+Math.round(sh*s.close).toLocaleString('en-IN');riskAmt='\\u20B9'+Math.round(sh*s.risk_per_share).toLocaleString('en-IN');}}
    const reasons=s.top_reasons.map(r=>`<li>${r}</li>`).join('');
    const cardClass=s.action==='EXIT'?'trade-card exit-card':'trade-card';
    document.getElementById('detailContent').innerHTML = `
        <div class="${cardClass}"><h3>${s.action==='ENTER'?'TRADE PLAN':s.action==='EXIT'?'EXIT SIGNAL':'NO TRADE'}</h3>
            <div class="trade-param"><span class="tp-label">Entry</span><span class="tp-value tp-entry">\\u20B9${fmt(s.close)}</span></div>
            <div class="trade-param"><span class="tp-label">Stop Loss</span><span class="tp-value tp-sl">\\u20B9${fmt(s.stop_loss)} (${fmt(s.sl_pct,1)}%)</span></div>
            <div class="trade-param"><span class="tp-label">Target (${s.resistance_type||'resistance'})</span><span class="tp-value tp-target">\\u20B9${fmt(s.target)} (+${fmt(s.target_pct,1)}%)</span></div>
            <div class="trade-param"><span class="tp-label">R:R</span><span class="tp-value ${rrClass(s.risk_reward)}">${s.risk_reward?s.risk_reward.toFixed(1)+':1':'N/A'}</span></div>
            <div class="trade-param"><span class="tp-label">Quantity</span><span class="tp-value tp-qty">${qty} shares</span></div>
            <div class="trade-param"><span class="tp-label">Investment</span><span class="tp-value">${investAmt}</span></div>
            <div class="trade-param"><span class="tp-label">Max Risk</span><span class="tp-value tp-sl">${riskAmt}</span></div>
        </div>
        <div class="detail-section"><h3>Action: ${s.action}</h3><p style="font-size:13px;color:#f0f3f6">${s.action_reason}</p></div>
        <div class="detail-section"><h3>Signal Breakdown</h3>
            <div class="detail-row"><span class="label">Technical</span><span class="value ${s.technical_score>0?'positive':'negative'}">${s.technical_score>=0?'+':''}${s.technical_score}/16 (${s.technical_action})</span></div>
            <div class="detail-row"><span class="label">Money Flow</span><span class="value ${s.money_flow_score>0?'positive':'negative'}">${s.money_flow_score>=0?'+':''}${s.money_flow_score}/10 (${s.money_flow_action})</span></div>
            <div class="detail-row"><span class="label">Combined</span><span class="value" style="font-weight:700;color:#58a6ff">${s.combined_score>=0?'+':''}${s.combined_score.toFixed(1)}</span></div>
        </div>
        <div class="detail-section"><h3>Key Signals</h3><ul class="reason-list">${reasons||'<li>No signals</li>'}</ul></div>
        <div class="detail-section"><h3>Support / Resistance</h3>
            <div class="detail-row"><span class="label">52W High</span><span class="value">${fmt(s.high_52w)} (${fmt(s.dist_from_52w_high,1)}%)</span></div>
            <div class="detail-row"><span class="label">Support</span><span class="value positive">${fmt(s.support_level)} (${s.support_type||'none'})</span></div>
            <div class="detail-row"><span class="label">Resistance</span><span class="value negative">${fmt(s.resistance_level)} (${s.resistance_type||'none'})</span></div>
            <div class="detail-row"><span class="label">ATR (14)</span><span class="value">${fmt(s.atr_14)}</span></div>
        </div>
        <div class="detail-section"><h3>Context</h3>
            <div class="detail-row"><span class="label">Sector</span><span class="value">${s.sector} / ${s.industry}</span></div>
            <div class="detail-row"><span class="label">Market</span><span class="value">${s.market_regime.toUpperCase()}</span></div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// TAB 4: OPPORTUNITIES
// ═══════════════════════════════════════════════════════════════
let oppCapital=1000000, oppRisk=1.0;

function updateOppCapital() {
    oppCapital = parseFloat(document.getElementById('opp-capitalInput').value)||1000000;
    oppRisk = parseFloat(document.getElementById('opp-riskPct').value)||1.0;
    document.getElementById('opp-maxRiskDisplay').textContent = '\\u20B9'+(oppCapital*oppRisk/100).toLocaleString('en-IN');
}

function renderOppCards(containerId, data, cardClass) {
    const container = document.getElementById(containerId);
    if (!data.length) { container.innerHTML='<div style="padding:20px;color:#8b949e;text-align:center">No opportunities found</div>'; return; }
    const maxRisk=oppCapital*oppRisk/100;
    container.innerHTML = data.map(s => {
        const techCls=s.tech_score>=3?'tech-pos':s.tech_score<=-2?'tech-neg':'tech-neutral';
        const flowCls=s.flow_score>=2?'flow-pos':s.flow_score<=-2?'flow-neg':'flow-neutral';
        const alignCls='align-'+s.alignment;
        const catCls='cat-'+(s.signal_category||'neutral');
        const catLabel=s.signal_category==='confirmed'?'CONFIRMED':s.signal_category==='early'?'EARLY':s.signal_category==='unconfirmed'?'UNCONFIRMED':s.signal_category==='trap'?'TRAP':'';
        const rrCls=s.risk_reward>=2.0?'rr-good':s.risk_reward>=1.0?'rr-ok':'rr-bad';
        let qty='-',riskAmt='-';
        if(s.risk_per_share&&s.risk_per_share>0){const sh=Math.floor(maxRisk/s.risk_per_share);if(sh>0){qty=sh;riskAmt='\\u20B9'+Math.round(sh*s.risk_per_share).toLocaleString('en-IN');}}
        const risks=s.risk_flags.map(r=>`<span class="risk-flag">${r}</span>`).join('');
        return `<div class="opp-card ${cardClass}" onclick='showOppDetail(${JSON.stringify(s).replace(/'/g,"&#39;")})'>
            <div class="opp-top">
                <div class="opp-ticker">${s.ticker}<span class="sector">${s.sector} / ${s.industry}</span></div>
                <div class="opp-price">\\u20B9${fmt(s.close)}</div>
                <div class="opp-scores"><span class="score-chip ${techCls}">Tech ${s.tech_score>=0?'+':''}${s.tech_score}</span><span class="score-chip ${flowCls}">Flow ${s.flow_score>=0?'+':''}${s.flow_score}</span></div>
                <span class="opp-alignment ${alignCls}">${s.alignment}</span>${catLabel?`<span class="cat-badge ${catCls}">${catLabel}</span>`:''}
                <div class="opp-rr"><div class="rr-val ${rrCls}">${s.risk_reward!==null?s.risk_reward.toFixed(1)+':1':'-'}</div><div class="rr-label">Risk:Reward</div></div>
            </div>
            <div class="opp-why">${s.primary_reason}</div>
            <div class="opp-levels">
                <span>SL: <b class="sl-val">\\u20B9${fmt(s.stop_loss)}</b> (${fmt(s.sl_pct,1)}%) <i>${s.sl_source}</i></span>
                <span>Target: <b class="tgt-val">\\u20B9${fmt(s.target)}</b> (+${fmt(s.target_pct,1)}%) <i>${s.target_source}</i></span>
                <span>Qty: <b class="qty-val">${qty}</b> | Risk: ${riskAmt}</span>
            </div>
            ${risks?'<div class="opp-risks">'+risks+'</div>':''}
        </div>`;
    }).join('');
}

function showOppDetail(s) {
    document.getElementById('detailPanel').style.display='block';
    document.getElementById('detailTicker').textContent = s.ticker + ' ('+s.sector+')';
    const maxRisk=oppCapital*oppRisk/100;
    let qty='-',investAmt='-',riskAmt='-';
    if(s.risk_per_share&&s.risk_per_share>0&&s.close){const sh=Math.floor(maxRisk/s.risk_per_share);if(sh>0){qty=sh;investAmt='\\u20B9'+Math.round(sh*s.close).toLocaleString('en-IN');riskAmt='\\u20B9'+Math.round(sh*s.risk_per_share).toLocaleString('en-IN');}}
    const reasons=s.secondary_reasons.map(r=>`<li>${r}</li>`).join('');
    const risks=s.risk_flags.map(r=>`<li style="color:#f0883e">${r}</li>`).join('');
    document.getElementById('detailContent').innerHTML = `
        <div class="detail-section"><h3>Alignment: ${s.alignment.toUpperCase()}</h3>
            <p style="font-size:13px;color:#f0f3f6">${s.alignment_label}</p>
            ${s.category_label?`<div style="margin-top:8px"><span class="cat-badge cat-${s.signal_category||'neutral'}" style="font-size:12px;padding:5px 12px">${s.category_label}</span></div>`:''}
            <div class="detail-row" style="margin-top:8px"><span class="label">Technical</span><span class="value ${s.tech_score>0?'positive':'negative'}">${s.tech_score>=0?'+':''}${s.tech_score}/${s.tech_max} (${s.tech_action})</span></div>
            <div class="detail-row"><span class="label">Money Flow</span><span class="value ${s.flow_score>0?'positive':'negative'}">${s.flow_score>=0?'+':''}${s.flow_score}/${s.flow_max} (${s.flow_action})</span></div>
        </div>
        <div class="detail-section"><h3>Trade Levels</h3>
            <div class="detail-row"><span class="label">Entry</span><span class="value" style="color:#58a6ff;font-weight:700">\\u20B9${fmt(s.close)}</span></div>
            <div class="detail-row"><span class="label">Stop Loss (${s.sl_source})</span><span class="value negative">\\u20B9${fmt(s.stop_loss)} (${fmt(s.sl_pct,1)}%)</span></div>
            <div class="detail-row"><span class="label">Target (${s.target_source})</span><span class="value positive">\\u20B9${fmt(s.target)} (+${fmt(s.target_pct,1)}%)</span></div>
            <div class="detail-row"><span class="label">R:R</span><span class="value" style="font-weight:700">${s.risk_reward?s.risk_reward.toFixed(1)+':1':'-'}</span></div>
            <div class="detail-row"><span class="label">Qty</span><span class="value" style="color:#d29922">${qty} shares</span></div>
            <div class="detail-row"><span class="label">Investment</span><span class="value">${investAmt}</span></div>
            <div class="detail-row"><span class="label">Max Risk</span><span class="value negative">${riskAmt}</span></div>
        </div>
        <div class="detail-section"><h3>Why</h3><ul class="reason-list">${reasons}</ul></div>
        <div class="detail-section"><h3>Risks</h3><ul class="reason-list">${risks||'<li style="color:#8b949e">No major risk flags</li>'}</ul></div>
        <div class="detail-section"><h3>Price Context</h3>
            <div class="detail-row"><span class="label">1D / 5D / 20D</span><span class="value">${fmt(s.change_1d,1)}% / ${fmt(s.change_5d,1)}% / ${fmt(s.change_20d,1)}%</span></div>
            <div class="detail-row"><span class="label">52W High</span><span class="value">\\u20B9${fmt(s.high_52w)} (${fmt(s.dist_from_52w_high,1)}%)</span></div>
            <div class="detail-row"><span class="label">Support</span><span class="value positive">\\u20B9${fmt(s.support)}</span></div>
            <div class="detail-row"><span class="label">Resistance</span><span class="value negative">\\u20B9${fmt(s.resistance)}</span></div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// DETAIL PANEL (shared)
// ═══════════════════════════════════════════════════════════════
function closeDetail() { document.getElementById('detailPanel').style.display='none'; }
document.addEventListener('keydown', e => { if (e.key==='Escape') closeDetail(); });

// ═══════════════════════════════════════════════════════════════
// SORTING (per-tab)
// ═══════════════════════════════════════════════════════════════
document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
        const tab = th.dataset.tab;
        const col = th.dataset.col;
        let sortState;
        if (tab==='tech') sortState=techSort;
        else if (tab==='mf') sortState=mfSort;
        else if (tab==='tp') sortState=tpSort;
        else return;

        if (sortState.col===col) { sortState.dir = sortState.dir==='asc'?'desc':'asc'; }
        else { sortState.col=col; sortState.dir = (col==='ticker'||col==='sector')?'asc':'desc'; }

        // Update header classes within this table
        th.closest('thead').querySelectorAll('th.sortable').forEach(h => h.classList.remove('sort-asc','sort-desc'));
        th.classList.add(sortState.dir==='asc'?'sort-asc':'sort-desc');

        // Re-render
        if (tab==='tech') filterTech();
        else if (tab==='mf') filterMF();
        else if (tab==='tp') renderTP(getTPFiltered());
    });
});

// ═══════════════════════════════════════════════════════════════
// ═══════════════════════════════════════════════════════════════
// TAB 6: VINOTH'S STRATEGY
// ═══════════════════════════════════════════════════════════════
function renderStratCards(containerId, data, zoneCls) {
    const container = document.getElementById(containerId);
    if (!data.length) { container.innerHTML='<div class="vs-no-data">No stocks in this zone currently</div>'; return; }
    container.innerHTML = data.map(s => {
        const zoneBadge = s.zone==='entry'?'ENTRY':'';
        const rsiColor = s.rsi<=30?'#f85149':s.rsi<=35?'#d29922':s.rsi<=42?'#d29922':'#8b949e';
        const histPct = s.macd_histogram!==null ? Math.min(Math.abs(s.macd_histogram)*10, 100) : 0;
        const histColor = s.macd_hist_direction==='rising'?'#3fb950':'#f85149';
        const convDays = s.macd_converging_days||0;
        const risks = (s.risk_flags||[]).map(r => '<span class="vs-risk-flag">'+r+'</span>').join('');

        let btChips = '';
        if (s.historical_trades > 0) {
            const wrCls = s.historical_win_rate >= 60 ? '' : s.historical_win_rate >= 40 ? '' : 'warn';
            const retCls = s.historical_avg_return >= 0 ? '' : 'warn';
            btChips = '<div class="vs-backtest">' +
                '<span class="vs-bt-chip '+wrCls+'">Win: '+s.historical_win_rate+'% ('+s.historical_trades+' trades)</span>' +
                '<span class="vs-bt-chip '+retCls+'">Avg 20D: '+(s.historical_avg_return>=0?'+':'')+s.historical_avg_return.toFixed(1)+'%</span>' +
                '</div>';
        }

        return '<div class="vs-card zone-'+s.zone+'">' +
            '<div class="vs-card-top">' +
                '<div class="vs-card-ticker">'+s.ticker+'<span class="sector">'+s.sector+' / '+s.industry+'</span></div>' +
                '<div class="vs-card-price">\\u20B9'+fmt(s.close)+'</div>' +
                '<div class="vs-indicators">' +
                    '<div class="vs-ind"><div class="vs-ind-val" style="color:'+rsiColor+'">'+fmt(s.rsi,1)+'</div><div class="vs-ind-label">RSI</div></div>' +
                    '<div class="vs-ind"><div class="vs-ind-val" style="color:#8b949e">'+fmt(s.macd_histogram,2)+'</div><div class="vs-ind-label">MACD Hist</div></div>' +
                    '<div class="vs-ind"><div class="vs-ind-val" style="color:'+histColor+'">'+convDays+'d</div><div class="vs-ind-label">Converging</div></div>' +
                '</div>' +
                (s.zone==='entry'?'<span class="vs-zone-badge vs-zone-entry">ENTER</span>':
                 s.zone==='near'?'<span class="vs-zone-badge vs-zone-near">WATCH</span>':
                 '<span class="vs-zone-badge vs-zone-crossed">RUNNING</span>') +
            '</div>' +
            '<div class="vs-card-label">'+s.zone_label+'</div>' +
            '<div class="vs-hist-bar">' +
                '<span class="vs-hist-label">MACD convergence:</span>' +
                '<div class="vs-hist-track"><div class="vs-hist-fill" style="width:'+histPct+'%;background:'+histColor+'"></div></div>' +
                '<span class="vs-hist-label">'+(s.macd_hist_direction||'')+'</span>' +
            '</div>' +
            (s.stop_loss ? '<div class="vs-card-levels" style="margin-top:8px">' +
                '<span>SL: <b style="color:#f85149">\\u20B9'+fmt(s.stop_loss)+'</b> ('+fmt(s.sl_pct,1)+'%)</span>' +
                '<span>Target 10D: <b style="color:#d29922">\\u20B9'+fmt(s.target_10d)+'</b></span>' +
                '<span>Target 20D: <b style="color:#3fb950">\\u20B9'+fmt(s.target_20d)+'</b></span>' +
                '<span>ATR: '+fmt(s.atr,1)+'</span>' +
            '</div>' : '') +
            btChips +
            (risks ? '<div class="vs-risks">'+risks+'</div>' : '') +
        '</div>';
    }).join('');
}

// INIT
// ═══════════════════════════════════════════════════════════════
function init() {
    // Tab 0: Action Brief
    renderActionBrief(ACTION_BRIEF);

    // Tab 1
    renderTech(TECH_DATA);
    document.getElementById('tech-actionFilter').onchange = filterTech;
    document.getElementById('tech-search').oninput = filterTech;
    document.getElementById('tech-minScore').oninput = filterTech;

    // Tab 2
    renderFiiDii();
    renderMF(MF_DATA);
    document.getElementById('mf-flowFilter').onchange = filterMF;
    document.getElementById('mf-search').oninput = filterMF;
    document.getElementById('mf-minScore').oninput = filterMF;

    // Tab 3
    updateCapital();
    renderSectorHeatmap();
    populateSectorFilter();
    renderTP(getTPFiltered());
    document.getElementById('tp-actionFilter').onchange = () => renderTP(getTPFiltered());
    document.getElementById('tp-search').oninput = () => renderTP(getTPFiltered());
    document.getElementById('tp-sectorFilter').onchange = () => renderTP(getTPFiltered());
    document.getElementById('tp-minRR').oninput = () => renderTP(getTPFiltered());
    document.getElementById('capitalInput').oninput = () => { updateCapital(); renderTP(getTPFiltered()); };
    document.getElementById('riskPct').onchange = () => { updateCapital(); renderTP(getTPFiltered()); };

    // Tab 4
    updateOppCapital();
    renderOppCards('buyCards', BUY_DATA, 'buy-card');
    renderOppCards('sellCards', SELL_DATA, 'sell-card');
    renderOppCards('mlCards', ML_DATA, 'ml-card');
    document.getElementById('opp-capitalInput').oninput = () => { updateOppCapital(); renderOppCards('buyCards',BUY_DATA,'buy-card'); renderOppCards('sellCards',SELL_DATA,'sell-card'); renderOppCards('mlCards',ML_DATA,'ml-card'); };
    document.getElementById('opp-riskPct').onchange = () => { updateOppCapital(); renderOppCards('buyCards',BUY_DATA,'buy-card'); renderOppCards('sellCards',SELL_DATA,'sell-card'); renderOppCards('mlCards',ML_DATA,'ml-card'); };

    // Tab 5: Flow Tracker
    ftPopulateSelect();
    ftRender();

    // Tab 6: Vinoth's Strategy
    renderStratCards('stratEntryCards', STRAT_ENTRY, 'zone-entry');
    renderStratCards('stratNearCards', STRAT_NEAR, 'zone-near');
    renderStratCards('stratCrossedCards', STRAT_CROSSED, 'zone-crossed');
}

// ═══════════════════════════════════════════════════════════════
// TAB 5: FLOW TRACKER
// ═══════════════════════════════════════════════════════════════
let ftCurrentTicker = FLOW_DATA.tickers[0] || '';
let ftCurrentFilter = 'day';
const FT_PERIOD_DAYS = { day: 1, week: 5, month: 22 };

function ftPopulateSelect(filter) {
    const sel = document.getElementById('ftStockSelect');
    const list = filter ? FLOW_DATA.tickers.filter(t => t.includes(filter.toUpperCase())) : FLOW_DATA.tickers;
    sel.innerHTML = list.map(t => {
        const s = FLOW_DATA.stocks[t];
        return `<option value="${t}" ${t === ftCurrentTicker ? 'selected' : ''}>${t} — ${s.sector}</option>`;
    }).join('');
    sel.onchange = function() { ftCurrentTicker = this.value; ftRender(); };
}

function ftFilterTickers(q) { ftPopulateSelect(q); }

function ftSetFilter(f, btn) {
    ftCurrentFilter = f;
    document.querySelectorAll('.ft-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    ftRender();
}

function ftS() { return FLOW_DATA.stocks[ftCurrentTicker] || {}; }

function ftGetFiltered() {
    const n = FT_PERIOD_DAYS[ftCurrentFilter];
    const all = ftS().daily_data || [];
    return all.slice(-n);
}

function ftFmt(v, dec) { if (v == null) return 'N/A'; return Number(v).toFixed(dec || 0); }
function ftFmtCr(v) { if (v == null) return 'N/A'; return Number(v).toFixed(2) + ' Cr'; }
function ftFmtLakh(v) {
    if (v == null) return 'N/A';
    if (v >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
    if (v >= 1e5) return (v / 1e5).toFixed(1) + ' L';
    return v.toLocaleString('en-IN');
}

function ftPillClass(signal) {
    if (!signal) return 'ft-pill-gray';
    const s = signal.toLowerCase();
    if (s.includes('inflow') || s.includes('accumulation') || s.includes('rising') || s.includes('bullish')) return 'ft-pill-green';
    if (s.includes('outflow') || s.includes('distribution') || s.includes('falling') || s.includes('bearish')) return 'ft-pill-red';
    if (s.includes('neutral') || s.includes('flat') || s.includes('none')) return 'ft-pill-gray';
    return 'ft-pill-yellow';
}

function ftRenderHeader() {
    const s = ftS();
    document.getElementById('ftStockMeta').innerHTML = `<span class="ft-sector-badge">${s.sector || ''} &middot; ${s.industry || ''}</span>`;
    const chg = s.last_change;
    const chgColor = (chg || 0) >= 0 ? '#56d364' : '#f85149';
    const chgStr = chg != null ? (chg >= 0 ? '+' : '') + ftFmt(chg, 2) + '%' : '';
    document.getElementById('ftPriceBlock').innerHTML = `<div class="ft-price">${s.last_close || 'N/A'}</div><div class="ft-change" style="color:${chgColor}">${chgStr}</div>`;
}

function ftRenderSummary() {
    const data = ftGetFiltered();
    const el = document.getElementById('ftSummaryCards');
    if (!data.length) { el.innerHTML = '<div class="ft-no-data" style="grid-column:1/-1">No delivery data</div>'; return; }
    const totalDelivCr = data.reduce((s,d) => s + d.delivered_value_cr, 0);
    const totalTurnoverCr = data.reduce((s,d) => s + d.turnover_cr, 0);
    const avgDelivPct = data.reduce((s,d) => s + d.delivery_pct, 0) / data.length;
    const priceChange = data.length > 1 ? ((data[data.length-1].close / data[0].close) - 1) * 100 : (data[0].change_pct || 0);
    const pc = priceChange >= 0 ? '#56d364' : '#f85149';
    el.innerHTML = `
        <div class="ft-summary-card"><div class="ft-summary-label">Delivered Value</div><div class="ft-summary-value" style="color:#58a6ff">${ftFmtCr(totalDelivCr)}</div><div class="ft-summary-sub">${data.length} day${data.length>1?'s':''}</div></div>
        <div class="ft-summary-card"><div class="ft-summary-label">Total Turnover</div><div class="ft-summary-value">${ftFmtCr(totalTurnoverCr)}</div><div class="ft-summary-sub">Delivery: ${ftFmt(avgDelivPct,1)}% avg</div></div>
        <div class="ft-summary-card"><div class="ft-summary-label">Avg Delivery %</div><div class="ft-summary-value" style="color:${avgDelivPct >= 60 ? '#56d364' : avgDelivPct >= 45 ? '#d29922' : '#f85149'}">${ftFmt(avgDelivPct,1)}%</div><div class="ft-summary-sub">${avgDelivPct >= 60 ? 'High (institutional)' : avgDelivPct >= 45 ? 'Moderate' : 'Low (speculative)'}</div></div>
        <div class="ft-summary-card"><div class="ft-summary-label">Price Change</div><div class="ft-summary-value" style="color:${pc}">${priceChange >= 0 ? '+' : ''}${ftFmt(priceChange,2)}%</div><div class="ft-summary-sub">${data[0].date}${data.length > 1 ? ' → ' + data[data.length-1].date : ''}</div></div>`;
}

function ftRenderFiiDii() {
    const fii = FLOW_DATA.fii_dii || {};
    const dates = fii.dates || {};
    const el = document.getElementById('ftFiiDiiContext');
    let fiiNet = 0, diiNet = 0, fiiBuy = 0, fiiSell = 0, diiBuy = 0, diiSell = 0, cnt = 0;
    for (const vals of Object.values(dates)) {
        fiiNet += vals.fii_net || 0; diiNet += vals.dii_net || 0;
        fiiBuy += vals.fii_buy || 0; fiiSell += vals.fii_sell || 0;
        diiBuy += vals.dii_buy || 0; diiSell += vals.dii_sell || 0;
        cnt++;
    }
    if (!cnt) { el.innerHTML = '<div class="ft-no-data">FII/DII data not available</div>'; return; }
    const fc = fiiNet >= 0 ? '#56d364' : '#f85149';
    const dc = diiNet >= 0 ? '#56d364' : '#f85149';
    el.innerHTML = `<div class="ft-context-bar">
        <div class="ft-context-item"><div class="ft-context-label">FII/FPI Net</div><div class="ft-context-value" style="color:${fc}">${fiiNet >= 0?'+':''}${ftFmtCr(fiiNet)}</div></div>
        <div class="ft-context-item"><div class="ft-context-label">FII Buy</div><div class="ft-context-value">${ftFmtCr(fiiBuy)}</div></div>
        <div class="ft-context-item"><div class="ft-context-label">FII Sell</div><div class="ft-context-value">${ftFmtCr(fiiSell)}</div></div>
        <div class="ft-context-item" style="border-left:1px solid #30363d;padding-left:20px;"><div class="ft-context-label">DII Net</div><div class="ft-context-value" style="color:${dc}">${diiNet >= 0?'+':''}${ftFmtCr(diiNet)}</div></div>
        <div class="ft-context-item"><div class="ft-context-label">DII Buy</div><div class="ft-context-value">${ftFmtCr(diiBuy)}</div></div>
        <div class="ft-context-item"><div class="ft-context-label">DII Sell</div><div class="ft-context-value">${ftFmtCr(diiSell)}</div></div>
    </div>`;
}

function ftWeeklyDelivPcts(dd) {
    const weeks = [];
    for (let i = 0; i < dd.length; i += 5) {
        const chunk = dd.slice(i, i + 5);
        if (chunk.length >= 3) { weeks.push(chunk.reduce((s,d) => s + d.delivery_pct, 0) / chunk.length); }
    }
    return weeks;
}

function ftWeekTrendArrow(weeks) {
    if (weeks.length < 2) return '<span style="color:#8b949e">—</span>';
    const mx = Math.max(...weeks, 1);
    let bars = '<span style="display:inline-flex;align-items:end;gap:1px;height:16px;vertical-align:middle;">';
    weeks.forEach((w, i) => {
        const h = Math.max(Math.round(w / mx * 14), 2);
        const isLast = i === weeks.length - 1;
        const c = isLast ? (w > weeks[i-1] ? '#56d364' : w < weeks[i-1] ? '#f85149' : '#8b949e') : '#30363d';
        bars += `<span style="display:inline-block;width:4px;height:${h}px;background:${c};border-radius:1px;"></span>`;
    });
    bars += '</span>';
    const first = weeks[0]; const last = weeks[weeks.length - 1];
    const chg = last - first;
    const arrow = chg > 2 ? '&#9650;' : chg < -2 ? '&#9660;' : '&#9654;';
    const ac = chg > 2 ? '#56d364' : chg < -2 ? '#f85149' : '#8b949e';
    return `${bars} <span style="color:${ac};font-size:10px;margin-left:3px;">${arrow} ${ftFmt(last,0)}%</span>`;
}

function ftRenderRanking() {
    const rankings = FLOW_DATA.tickers.map(t => {
        const s = FLOW_DATA.stocks[t];
        const dd = s.daily_data || [];
        const month = dd.slice(-22);
        const delivCr = month.reduce((sum,d) => sum + d.delivered_value_cr, 0);
        const avgDP = month.length ? month.reduce((sum,d) => sum + d.delivery_pct, 0) / month.length : 0;
        const priceChg = month.length > 1 ? ((month[month.length-1].close / month[0].close) - 1) * 100 : 0;
        const mcap = s.mcap_cr;
        const delivMcapPct = mcap > 0 ? (delivCr / mcap) * 100 : null;
        const weeks = ftWeeklyDelivPcts(month);
        return { ticker: t, sector: s.sector, delivCr, avgDP, priceChg, mcap, delivMcapPct, weeks };
    }).sort((a,b) => b.delivCr - a.delivCr);

    const el = document.getElementById('ftRankTable');
    let html = `<table><thead><tr><th>#</th><th>Ticker</th><th>Sector</th><th style="text-align:right">Deliv Value</th><th style="text-align:right">Del/MCap</th><th style="text-align:right">Avg Del%</th><th>Del% Trend (W/W)</th><th style="text-align:right">Price</th></tr></thead><tbody>`;
    rankings.forEach((r, i) => {
        const sel = r.ticker === ftCurrentTicker ? ' class="selected"' : '';
        const pc = r.priceChg >= 0 ? '#56d364' : '#f85149';
        const dc = r.avgDP >= 60 ? '#56d364' : r.avgDP >= 45 ? '#d29922' : '#f85149';
        const dmPct = r.delivMcapPct;
        const dmc = dmPct != null ? (dmPct >= 3 ? '#bc8cff' : dmPct >= 1.5 ? '#58a6ff' : '#8b949e') : '#8b949e';
        const trendHtml = ftWeekTrendArrow(r.weeks);
        html += `<tr${sel} onclick="document.getElementById('ftStockSelect').value='${r.ticker}';ftCurrentTicker='${r.ticker}';ftRender()">
            <td>${i+1}</td><td style="font-weight:600;color:#58a6ff">${r.ticker}</td><td style="color:#8b949e;font-size:10px">${r.sector}</td>
            <td style="text-align:right;color:#58a6ff">${ftFmtCr(r.delivCr)}</td>
            <td style="text-align:right;color:${dmc};font-weight:600">${dmPct != null ? ftFmt(dmPct, 2) + '%' : 'N/A'}</td>
            <td style="text-align:right;color:${dc}">${ftFmt(r.avgDP,1)}%</td>
            <td>${trendHtml}</td>
            <td style="text-align:right;color:${pc}">${r.priceChg >= 0?'+':''}${ftFmt(r.priceChg,1)}%</td>
        </tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

function ftRenderDeals() {
    const el = document.getElementById('ftDealsPanel');
    // Collect deals from ALL Nifty 100 stocks
    let allDeals = [];
    for (const t of FLOW_DATA.tickers) {
        const deals = (FLOW_DATA.stocks[t].deals || []);
        for (const d of deals) { allDeals.push(Object.assign({ticker: t}, d)); }
    }
    if (!allDeals.length) { el.innerHTML = '<div class="ft-no-data">No bulk/block deals across Nifty 100</div>'; return; }
    // Sort by date descending, then by value descending
    allDeals.sort((a,b) => (b.date||'').localeCompare(a.date||'') || (b.value_cr||0) - (a.value_cr||0));
    el.innerHTML = allDeals.map(d => `<div class="ft-deal-card">
        <div class="ft-deal-header"><span class="ft-deal-client" style="font-weight:700;color:#58a6ff">${d.ticker}</span>
            <span class="ft-deal-client" style="margin-left:8px">${d.client}</span>
            <span class="ft-pill ${d.deal_type==='BUY'?'ft-pill-green':'ft-pill-red'}">${d.deal_type}</span></div>
        <div class="ft-deal-meta">${d.date} &middot; ${d.source.toUpperCase()} &middot; ${ftFmtLakh(d.quantity)} @ ${ftFmt(d.price,2)} &middot; <strong>${ftFmtCr(d.value_cr)}</strong></div>
    </div>`).join('');
}

function ftRenderDailyTable() {
    const data = ftGetFiltered();
    const el = document.getElementById('ftDailyTable');
    if (!data.length) { el.innerHTML = '<div class="ft-no-data">No data</div>'; return; }
    const rows = [...data].reverse();
    let h = `<table><thead><tr><th>Date</th><th style="text-align:right">Close</th><th style="text-align:right">Chg</th><th style="text-align:right">Volume</th><th style="text-align:right">Deliv Qty</th><th style="text-align:right">Del%</th><th style="text-align:right">Deliv Value</th><th style="text-align:right">Turnover</th></tr></thead><tbody>`;
    for (const d of rows) {
        const cc = (d.change_pct||0)>=0?'#56d364':'#f85149';
        const dc = d.delivery_pct>=60?'#56d364':d.delivery_pct>=45?'#d29922':'#f85149';
        h += `<tr><td>${d.date}</td><td style="text-align:right">${ftFmt(d.close,2)}</td>
            <td style="text-align:right;color:${cc}">${d.change_pct!=null?(d.change_pct>=0?'+':'')+ftFmt(d.change_pct,2)+'%':''}</td>
            <td style="text-align:right">${ftFmtLakh(d.volume)}</td><td style="text-align:right">${ftFmtLakh(d.delivery_qty)}</td>
            <td style="text-align:right;color:${dc};font-weight:600">${ftFmt(d.delivery_pct,1)}%</td>
            <td style="text-align:right;color:#58a6ff;font-weight:500">${ftFmtCr(d.delivered_value_cr)}</td>
            <td style="text-align:right">${ftFmtCr(d.turnover_cr)}</td></tr>`;
    }
    h += '</tbody></table>';
    el.innerHTML = h;
}

function ftRender() {
    ftRenderHeader();
    ftRenderSummary();
    ftRenderFiiDii();
    ftRenderRanking();
    ftRenderDeals();
    ftRenderDailyTable();
}

init();
"""
