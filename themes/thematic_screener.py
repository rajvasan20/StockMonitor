"""Modernized thematic screener — adapted from Graham's principles.

Graham's quality gate stays. His valuation thresholds get
sector-contextualized for high-growth thematic plays.

Keeps:
    - All earnings quality checks (Security Analysis)
    - Value trap detection (7 checks)
    - Financial strength requirements
    - Pairwise comparison framework within segments

Replaces:
    - P/E <= 9          -> PEG <= 1.5 OR P/E < sector median
    - Price < 120% NTA  -> EV/EBITDA < sector median
    - No deficit 5yr    -> ROCE > 12% and improving
    - Some dividend     -> Optional (growth > dividends)

Adds:
    - Capex/Revenue trend (rising capex = positive for infra themes)
    - Revenue CAGR >= 15% (3yr) for growth proof
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from shared.scraper import ScreenerScraper
from shared.data_parser import (
    parse_company_page, get_ratio, get_cmp, get_latest_annual,
    get_value_series, get_ttm_value, get_debt_to_equity,
    get_avg_roce, get_avg_roe, get_fcf_series,
    get_promoter_holding, get_shares_outstanding,
)
from shared.utils import growth_rate, mean, median, logger
from shared.sector_profiles import get_sector_profile
from universe_monitor.valuation_engine import run_all_valuations
from universe_monitor.value_trap import detect_value_traps
from themes.registry import (
    get_theme, get_all_themes, Theme, THEMES,
)


@dataclass
class ThematicCheck:
    name: str
    passed: bool
    value: Optional[str] = None
    threshold: Optional[str] = None
    notes: str = ""


@dataclass
class ThematicScreenResult:
    ticker: str
    company_name: str
    theme: str
    segment: str
    exposure: str           # high, medium, low
    cmp: Optional[float] = None
    sector: str = ""

    # Individual checks
    checks: List[ThematicCheck] = field(default_factory=list)
    checks_passed: int = 0
    checks_total: int = 0

    # Valuation context
    composite_iv: Optional[float] = None
    upside_pct: Optional[float] = None
    verdict: str = ""

    # Value trap
    value_trap_label: str = ""
    value_trap_flags: List[str] = field(default_factory=list)

    # Overall grade
    grade: str = "D"        # A, B, C, D

    @property
    def grade_label(self) -> str:
        labels = {"A": "STRONG BUY", "B": "BUY", "C": "WATCHLIST", "D": "AVOID"}
        return labels.get(self.grade, "AVOID")


# ── Thematic screening thresholds ────────────────────────────────────────────

THEMATIC_THRESHOLDS = {
    "peg_max": 1.5,
    "roce_min": 12.0,          # % — minimum acceptable ROCE
    "revenue_cagr_min": 0.15,  # 15% 3-year CAGR
    "de_max": 1.5,             # higher tolerance for capex-heavy themes
    "current_ratio_min": 1.2,  # slightly relaxed from Graham's 1.5
    "interest_coverage_min": 3.0,
    "cfo_profit_min": 0.60,    # cash flow backing profits
}


def screen_theme(theme_slug: str, use_cache: bool = True) -> List[ThematicScreenResult]:
    """Screen all companies in a theme. Returns sorted by grade."""
    theme = get_theme(theme_slug)
    if not theme:
        logger.error(f"Theme '{theme_slug}' not found")
        return []

    logger.info(f"Screening theme: {theme.name} ({len(theme.all_tickers)} tickers)")
    scraper = ScreenerScraper()
    results = []

    for seg in theme.segments:
        for co in seg.companies:
            logger.info(f"  Screening {co.ticker} ({co.name})...")
            try:
                result = _screen_single(
                    scraper, co.ticker, theme.name, seg.name,
                    co.exposure, co.name,
                )
                results.append(result)
            except Exception as e:
                logger.error(f"  Error screening {co.ticker}: {e}")
                results.append(ThematicScreenResult(
                    ticker=co.ticker,
                    company_name=co.name,
                    theme=theme.name,
                    segment=seg.name,
                    exposure=co.exposure,
                    grade="D",
                ))

    results.sort(key=lambda r: ("ABCD".index(r.grade), -_exposure_rank(r.exposure)))
    return results


def screen_all_themes() -> Dict[str, List[ThematicScreenResult]]:
    """Screen all themes. Returns dict of theme_slug -> results."""
    return {slug: screen_theme(slug) for slug in THEMES}


def compare_within_segment(theme_slug: str, segment_name: str) -> List[Dict]:
    """Pairwise comparison within a segment — Graham Chapter 18 style.

    Returns companies ranked on 9 dimensions with relative scores.
    """
    theme = get_theme(theme_slug)
    if not theme:
        return []

    seg = next((s for s in theme.segments if s.name == segment_name), None)
    if not seg or len(seg.companies) < 2:
        return []

    scraper = ScreenerScraper()
    company_data = []

    for co in seg.companies:
        html, variant = scraper.fetch_company_html(co.ticker)
        if html is None:
            continue
        data = parse_company_page(html, co.ticker)
        if not data.get("top_ratios"):
            continue
        company_data.append((co, data))

    if len(company_data) < 2:
        return []

    comparisons = []
    for co, data in company_data:
        profile = get_sector_profile(data.get("sector"))
        metrics = _extract_comparison_metrics(data, profile)
        metrics["ticker"] = co.ticker
        metrics["name"] = co.name
        metrics["exposure"] = co.exposure
        comparisons.append(metrics)

    # Rank on each dimension (lower rank = better)
    dimensions = [
        "pe", "pb", "peg", "ev_ebitda", "dividend_yield",
        "roce", "roe", "revenue_cagr_3y", "profit_cagr_3y",
        "current_ratio", "de_ratio", "interest_coverage",
        "promoter_holding", "cfo_profit_ratio",
    ]

    for dim in dimensions:
        values = [(i, c.get(dim)) for i, c in enumerate(comparisons)]
        values = [(i, v) for i, v in values if v is not None]

        # Determine if lower or higher is better
        lower_is_better = dim in ("pe", "pb", "peg", "ev_ebitda", "de_ratio")
        values.sort(key=lambda x: x[1], reverse=not lower_is_better)

        for rank, (idx, _) in enumerate(values):
            comparisons[idx][f"{dim}_rank"] = rank + 1

    # Composite rank
    for c in comparisons:
        ranks = [c.get(f"{d}_rank", len(comparisons)) for d in dimensions]
        c["composite_rank"] = sum(ranks) / len(ranks)

    comparisons.sort(key=lambda c: c["composite_rank"])
    return comparisons


# ── Internal helpers ─────────────────────────────────────────────────────────

def _screen_single(scraper, ticker, theme_name, segment_name,
                    exposure, company_name) -> ThematicScreenResult:
    """Screen a single ticker against thematic criteria."""
    result = ThematicScreenResult(
        ticker=ticker,
        company_name=company_name,
        theme=theme_name,
        segment=segment_name,
        exposure=exposure,
    )

    html, variant = scraper.fetch_company_html(ticker)
    if html is None:
        result.checks.append(ThematicCheck("Data Availability", False,
                                           notes="Not found on Screener.in"))
        return result

    data = parse_company_page(html, ticker)
    if not data.get("top_ratios"):
        result.checks.append(ThematicCheck("Data Availability", False,
                                           notes="No financial data"))
        return result

    result.cmp = get_cmp(data)
    result.sector = data.get("sector", "")
    profile = get_sector_profile(result.sector)
    T = THEMATIC_THRESHOLDS

    # ── Check 1: Revenue Growth (3yr CAGR >= 15%) ────────────────────────
    sales = get_value_series(data, "profit_loss", "Sales", n_years=5)
    sales_3y = sales[-4:] if sales and len(sales) >= 4 else sales
    rev_cagr = growth_rate(sales_3y) if sales_3y and len(sales_3y) >= 2 else None
    result.checks.append(ThematicCheck(
        "Revenue Growth",
        rev_cagr is not None and rev_cagr >= T["revenue_cagr_min"],
        f"{rev_cagr*100:.1f}%" if rev_cagr else "N/A",
        f">= {T['revenue_cagr_min']*100:.0f}%",
    ))

    # ── Check 2: ROCE > 12% (or improving trend) ────────────────────────
    roce = get_avg_roce(data, n_years=3)
    roce_series = get_value_series(data, "ratios", "ROCE %", n_years=5)
    roce_improving = False
    if roce_series and len(roce_series) >= 3:
        early = mean(roce_series[:2])
        recent = mean(roce_series[-2:])
        if early and recent and recent > early:
            roce_improving = True

    roce_pass = (roce is not None and roce >= T["roce_min"]) or roce_improving
    result.checks.append(ThematicCheck(
        "Capital Efficiency (ROCE)",
        roce_pass,
        f"{roce:.1f}%" if roce else "N/A",
        f">= {T['roce_min']:.0f}% or improving",
        "Improving trend" if roce_improving and (roce is None or roce < T["roce_min"]) else "",
    ))

    # ── Check 3: PEG <= 1.5 OR P/E < sector median ──────────────────────
    pe = get_ratio(data, "Stock P/E")
    np_series = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    earnings_growth = growth_rate(np_series) if np_series and len(np_series) >= 3 else None
    peg = pe / (earnings_growth * 100) if pe and earnings_growth and earnings_growth > 0 else None

    sector_pe_mid = sum(profile.pe_range) / 2
    peg_pass = (peg is not None and peg <= T["peg_max"])
    pe_pass = (pe is not None and pe < sector_pe_mid)
    valuation_pass = peg_pass or pe_pass

    val_value = f"PEG={peg:.2f}" if peg else f"P/E={pe:.1f}" if pe else "N/A"
    val_threshold = f"PEG <= {T['peg_max']} or P/E < {sector_pe_mid:.0f}"
    result.checks.append(ThematicCheck(
        "Valuation Reasonableness", valuation_pass,
        val_value, val_threshold,
    ))

    # ── Check 4: EV/EBITDA vs sector range ───────────────────────────────
    ev_low, ev_high = profile.ev_ebitda_range
    ev_mid = (ev_low + ev_high) / 2
    # Approximate EV/EBITDA from available data
    mcap = get_ratio(data, "Market Cap")
    borrowings = get_latest_annual(data, "balance_sheet", "Borrowings") or 0
    op_profit = get_ttm_value(data, "profit_loss", "Operating Profit")
    if op_profit is None:
        op_profit = get_latest_annual(data, "profit_loss", "Operating Profit")
    depreciation = get_ttm_value(data, "profit_loss", "Depreciation")
    if depreciation is None:
        depreciation = get_latest_annual(data, "profit_loss", "Depreciation") or 0

    ev_ebitda = None
    if mcap and op_profit and op_profit > 0:
        ebitda = op_profit + abs(depreciation or 0)
        ev = mcap + borrowings
        ev_ebitda = ev / ebitda if ebitda > 0 else None

    ev_pass = ev_ebitda is not None and ev_ebitda <= ev_high
    result.checks.append(ThematicCheck(
        "EV/EBITDA vs Sector",
        ev_pass,
        f"{ev_ebitda:.1f}x" if ev_ebitda else "N/A",
        f"<= {ev_high}x (sector range {ev_low}-{ev_high}x)",
    ))

    # ── Check 5: Financial Strength (D/E < 1.5, CR >= 1.2) ──────────────
    de = get_debt_to_equity(data)
    if de is None:
        de = get_ratio(data, "Debt to equity")

    cr_series = get_value_series(data, "ratios", "Current Ratio", n_years=3)
    cr = cr_series[-1] if cr_series else None

    de_ok = de is None or de <= T["de_max"]
    cr_ok = cr is None or cr >= T["current_ratio_min"]
    strength_pass = de_ok and cr_ok

    strength_val = []
    if de is not None:
        strength_val.append(f"D/E={de:.2f}")
    if cr is not None:
        strength_val.append(f"CR={cr:.2f}")

    result.checks.append(ThematicCheck(
        "Financial Strength", strength_pass,
        ", ".join(strength_val) if strength_val else "N/A",
        f"D/E <= {T['de_max']}, CR >= {T['current_ratio_min']}",
    ))

    # ── Check 6: Cash Flow Quality (CFO/Profit >= 60%) ───────────────────
    profits = get_value_series(data, "profit_loss", "Net Profit", n_years=3)
    cfo = get_value_series(data, "cash_flow", "Cash from Operating Activity", n_years=3)
    cfo_ratio = None
    if profits and cfo:
        n = min(len(profits), len(cfo))
        cum_profit = sum(p for p in profits[-n:] if p and p > 0)
        cum_cfo = sum(c for c in cfo[-n:] if c is not None)
        if cum_profit > 0:
            cfo_ratio = cum_cfo / cum_profit

    cfo_pass = cfo_ratio is not None and cfo_ratio >= T["cfo_profit_min"]
    result.checks.append(ThematicCheck(
        "Cash Flow Quality",
        cfo_pass,
        f"{cfo_ratio:.0%}" if cfo_ratio is not None else "N/A",
        f">= {T['cfo_profit_min']:.0%}",
    ))

    # ── Check 7: Capex Trend (positive for infra themes) ─────────────────
    # For infra-driven themes, growing capex is GOOD — it means the company
    # is investing to capture the opportunity
    capex_series = get_value_series(data, "cash_flow",
                                    "Fixed Assets Purchased", n_years=5)
    if not capex_series:
        capex_series = get_value_series(data, "cash_flow",
                                        "Capital Expenditure", n_years=5)
    # Capex is usually negative in cash flow; take absolute
    if capex_series:
        capex_series = [abs(v) for v in capex_series if v is not None]

    capex_growing = False
    if capex_series and len(capex_series) >= 3:
        capex_cagr = growth_rate(capex_series)
        if capex_cagr is not None and capex_cagr > 0.05:
            capex_growing = True

    # Check capex/revenue ratio is healthy (not overextending)
    capex_rev_ok = True
    if capex_series and sales:
        latest_capex = capex_series[-1] if capex_series else 0
        latest_sales = sales[-1] if sales else 0
        if latest_sales and latest_sales > 0 and latest_capex / latest_sales > 0.50:
            capex_rev_ok = False

    capex_pass = capex_growing and capex_rev_ok
    result.checks.append(ThematicCheck(
        "Capex Trend",
        capex_pass,
        "Growing" if capex_growing else "Flat/Declining",
        "Rising capex + capex/revenue < 50%",
        "Capex > 50% of revenue — overextension risk" if not capex_rev_ok else "",
    ))

    # ── Check 8: Promoter Holding Stable ─────────────────────────────────
    promoter = get_promoter_holding(data)
    from shared.data_parser import get_promoter_holding_series
    ph_series = get_promoter_holding_series(data)
    ph_stable = True
    if ph_series and len(ph_series) >= 4:
        decline = (ph_series[0] or 0) - (ph_series[-1] or 0)
        if decline > 3.0:
            ph_stable = False

    result.checks.append(ThematicCheck(
        "Promoter Holding Stable",
        ph_stable,
        f"{promoter:.1f}%" if promoter else "N/A",
        "No > 3pp decline",
    ))

    # ── Value trap check ─────────────────────────────────────────────────
    trap = detect_value_traps(data)
    result.value_trap_label = trap.label
    result.value_trap_flags = trap.flags

    # ── Valuation (full engine) ──────────────────────────────────────────
    val_summary = run_all_valuations(data)
    result.composite_iv = val_summary.composite_iv
    result.upside_pct = val_summary.upside_pct
    result.verdict = val_summary.verdict

    # ── Compute grade ────────────────────────────────────────────────────
    passed = sum(1 for c in result.checks if c.passed)
    total = len(result.checks)
    result.checks_passed = passed
    result.checks_total = total

    # Determine grade
    trap_penalty = trap.label == "LIKELY TRAP"

    if trap_penalty:
        result.grade = "D"
    elif passed >= 7:
        result.grade = "A"
    elif passed >= 5:
        result.grade = "B"
    elif passed >= 3:
        result.grade = "C"
    else:
        result.grade = "D"

    # Boost grade for high-exposure + undervalued
    if (result.grade == "B" and exposure == "high"
            and result.upside_pct is not None and result.upside_pct >= 0.20):
        result.grade = "A"

    logger.info(f"  {ticker}: Grade {result.grade} ({passed}/{total} checks, "
                f"{result.verdict}, trap={trap.label})")
    return result


def _extract_comparison_metrics(data, profile) -> Dict:
    """Extract all metrics needed for pairwise comparison."""
    pe = get_ratio(data, "Stock P/E")
    pb = get_ratio(data, "Price to book value") or (
        get_cmp(data) / get_ratio(data, "Book Value")
        if get_cmp(data) and get_ratio(data, "Book Value") and get_ratio(data, "Book Value") > 0
        else None
    )
    div_yield = get_ratio(data, "Dividend Yield")
    roce = get_avg_roce(data, n_years=3)
    roe = get_avg_roe(data, n_years=3)

    sales = get_value_series(data, "profit_loss", "Sales", n_years=5)
    sales_3y = sales[-4:] if sales and len(sales) >= 4 else sales
    rev_cagr = growth_rate(sales_3y) if sales_3y and len(sales_3y) >= 2 else None

    np_series = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    np_3y = np_series[-4:] if np_series and len(np_series) >= 4 else np_series
    profit_cagr = growth_rate(np_3y) if np_3y and len(np_3y) >= 2 else None

    earnings_growth = growth_rate(np_series) if np_series and len(np_series) >= 3 else None
    peg = pe / (earnings_growth * 100) if pe and earnings_growth and earnings_growth > 0 else None

    de = get_debt_to_equity(data)
    cr_series = get_value_series(data, "ratios", "Current Ratio", n_years=3)
    cr = cr_series[-1] if cr_series else None

    mcap = get_ratio(data, "Market Cap")
    borrowings = get_latest_annual(data, "balance_sheet", "Borrowings") or 0
    op_profit = get_ttm_value(data, "profit_loss", "Operating Profit")
    if op_profit is None:
        op_profit = get_latest_annual(data, "profit_loss", "Operating Profit")
    depreciation = get_latest_annual(data, "profit_loss", "Depreciation") or 0

    ev_ebitda = None
    if mcap and op_profit and op_profit > 0:
        ebitda = op_profit + abs(depreciation)
        ev = mcap + borrowings
        ev_ebitda = ev / ebitda if ebitda > 0 else None

    # Interest coverage
    interest = get_latest_annual(data, "profit_loss", "Interest")
    ebit = op_profit
    interest_coverage = None
    if ebit and interest and interest > 0:
        interest_coverage = ebit / interest

    promoter = get_promoter_holding(data)

    profits = get_value_series(data, "profit_loss", "Net Profit", n_years=3)
    cfo = get_value_series(data, "cash_flow", "Cash from Operating Activity", n_years=3)
    cfo_ratio = None
    if profits and cfo:
        n = min(len(profits), len(cfo))
        cum_profit = sum(p for p in profits[-n:] if p and p > 0)
        cum_cfo = sum(c for c in cfo[-n:] if c is not None)
        if cum_profit > 0:
            cfo_ratio = cum_cfo / cum_profit

    return {
        "pe": pe,
        "pb": pb,
        "peg": peg,
        "ev_ebitda": ev_ebitda,
        "dividend_yield": div_yield,
        "roce": roce,
        "roe": roe,
        "revenue_cagr_3y": rev_cagr,
        "profit_cagr_3y": profit_cagr,
        "current_ratio": cr,
        "de_ratio": de,
        "interest_coverage": interest_coverage,
        "promoter_holding": promoter,
        "cfo_profit_ratio": cfo_ratio,
        "market_cap": mcap,
    }


def _exposure_rank(exposure: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(exposure, 0)
