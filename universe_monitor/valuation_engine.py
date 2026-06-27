"""5-method valuation engine for Indian equities — sector-aware.

Methods:
    1. Graham Number
    2. DCF (Discounted Cash Flow) — uses actual FCF
    3. PEG Ratio — quality-adjusted P/E floor
    4. EV/EBITDA — sector-specific multiples
    5. Earnings Power Value (EPV)

Each method produces an intrinsic value. The final composite IV is a
weighted average (not a simple median), with weights driven by sector
profiles that reflect which methods are most appropriate for each
business type.
"""

import math
from dataclasses import dataclass, field
from typing import Optional, List

from config import (
    TERMINAL_GROWTH_RATE,
    BARGAIN_MIN_METHODS_AGREE,
    BARGAIN_UPSIDE_THRESHOLD, BARGAIN_MAX_DE_RATIO,
)
from shared.data_parser import (
    get_ratio, get_latest_annual, get_ttm_value,
    get_value_series, get_cmp, get_shares_outstanding,
    get_fcf_series, get_eps_series, get_debt_to_equity,
    get_pb_ratio, get_avg_roce, get_avg_roe,
    get_promoter_holding,
)
from shared.utils import growth_rate, median, mean, logger
from shared.sector_profiles import (
    get_sector_profile, get_quality_adjusted_peg_floor,
    BANK_METHOD_WEIGHTS,
)


@dataclass
class ValuationResult:
    method: str
    intrinsic_value: Optional[float] = None
    weight: float = 0.0              # sector-driven weight
    confidence: str = "low"          # high, medium, low
    notes: str = ""
    data_quality: str = "insufficient"  # complete, partial, insufficient


@dataclass
class ValuationSummary:
    ticker: str
    cmp: float
    sector: str = ""
    industry: str = ""
    results: List[ValuationResult] = field(default_factory=list)
    # Composite (weighted) IV replaces simple median
    composite_iv: Optional[float] = None
    median_iv: Optional[float] = None   # kept for reference
    upside_pct: Optional[float] = None
    methods_above_cmp: int = 0
    verdict: str = "INSUFFICIENT DATA"
    is_bargain: bool = False
    # Historical P/E context
    pe_current: Optional[float] = None
    pe_5yr_avg: Optional[float] = None
    pe_5yr_low: Optional[float] = None
    pe_5yr_high: Optional[float] = None
    pe_position: str = ""             # "Below avg", "Near avg", "Above avg"
    # Value trap
    value_trap_flags: List[str] = field(default_factory=list)
    value_trap_score: int = 0
    value_trap_label: str = ""


def run_all_valuations(data):
    """Run all 5 valuation methods with sector awareness. Returns ValuationSummary."""
    ticker = data.get("ticker", "???")
    cmp = get_cmp(data)
    sector = data.get("sector") or ""
    industry = data.get("industry") or ""

    if cmp is None or cmp <= 0:
        logger.warning(f"{ticker}: No valid CMP found")
        return ValuationSummary(ticker=ticker, cmp=0, sector=sector, industry=industry)

    profile = get_sector_profile(sector)
    roe = get_ratio(data, "ROE")

    # ── Select method set: bank-specific vs standard ────────────────
    use_bank_methods = (sector == "Financial Services")

    if use_bank_methods:
        methods = [
            (_bank_gordon_pb, "Gordon Growth P/B"),
            (_bank_justified_pe, "Justified P/E"),
            (_bank_ddm, "Dividend Discount"),
            (_bank_residual_income, "Residual Income"),
            (_bank_pb_reversion, "P/B Mean Reversion"),
        ]
        weight_map = BANK_METHOD_WEIGHTS
    else:
        methods = [
            (_graham_number, "Graham Number"),
            (_dcf, "DCF"),
            (_peg_valuation, "PEG Ratio"),
            (_ev_ebitda, "EV/EBITDA"),
            (_epv, "Earnings Power Value"),
        ]
        weight_map = profile.method_weights

    results = []
    for method_fn, method_name in methods:
        try:
            result = method_fn(data, cmp, profile, roe)
            result.weight = weight_map.get(method_name, 0.15)
            results.append(result)
        except Exception as e:
            results.append(ValuationResult(
                method=method_name,
                notes=f"Error: {e}",
                weight=weight_map.get(method_name, 0.15),
            ))

    # ── Composite IV (weighted) ──────────────────────────────────────────
    valid_results = [r for r in results
                     if r.intrinsic_value is not None and r.intrinsic_value > 0]
    valid_ivs = [r.intrinsic_value for r in valid_results]
    methods_above = sum(1 for iv in valid_ivs if iv > cmp)

    composite_iv = _compute_weighted_iv(valid_results)
    med_iv = median(valid_ivs)

    # Use composite as primary; fall back to median if composite fails
    primary_iv = composite_iv or med_iv
    upside = ((primary_iv / cmp) - 1) if primary_iv and cmp > 0 else None

    # ── Historical P/E context ───────────────────────────────────────────
    pe_current, pe_5yr_avg, pe_5yr_low, pe_5yr_high, pe_position = (
        _historical_pe_context(data, cmp, profile)
    )

    # ── Verdict — sector-aware ───────────────────────────────────────────
    if len(valid_ivs) < 3:
        verdict = "INSUFFICIENT DATA"
    elif upside is not None and upside >= BARGAIN_UPSIDE_THRESHOLD and methods_above >= BARGAIN_MIN_METHODS_AGREE:
        verdict = "BARGAIN"
    elif upside is not None and upside >= 0.10:
        verdict = "UNDERVALUED"
    elif upside is not None and upside >= -0.10:
        verdict = "FAIR VALUE"
    else:
        verdict = "OVERVALUED"

    # If historical P/E says it's cheap for this stock's own history,
    # and composite says fair/overvalued, soften to at most FAIR VALUE
    if (verdict == "OVERVALUED" and pe_position == "Below average"
            and upside is not None and upside >= -0.25):
        verdict = "FAIR VALUE"

    # Bargain check (stricter)
    eps_ttm = _get_eps(data)
    if use_bank_methods:
        # For banks: skip D/E check (deposits inflate it), check ROE instead
        is_bargain = (
            verdict == "BARGAIN"
            and (eps_ttm is not None and eps_ttm > 0)
            and (roe is not None and roe > 8)  # ROE > 8% = profitable bank
        )
    else:
        de_ratio = get_debt_to_equity(data)
        if de_ratio is None:
            de_ratio = get_ratio(data, "Debt to equity")
        is_bargain = (
            verdict == "BARGAIN"
            and (eps_ttm is not None and eps_ttm > 0)
            and (de_ratio is None or de_ratio < BARGAIN_MAX_DE_RATIO)
        )

    return ValuationSummary(
        ticker=ticker,
        cmp=cmp,
        sector=sector,
        industry=industry,
        results=results,
        composite_iv=composite_iv,
        median_iv=med_iv,
        upside_pct=upside,
        methods_above_cmp=methods_above,
        verdict=verdict,
        is_bargain=is_bargain,
        pe_current=pe_current,
        pe_5yr_avg=pe_5yr_avg,
        pe_5yr_low=pe_5yr_low,
        pe_5yr_high=pe_5yr_high,
        pe_position=pe_position,
    )


# ──────────────────────────────────────────────────────────
# Weighted composite IV
# ──────────────────────────────────────────────────────────

def _compute_weighted_iv(valid_results):
    """Compute weighted average IV using sector-driven method weights.

    Only includes methods that produced a valid IV. Re-normalizes weights
    so they sum to 1.0 across available methods.
    """
    if not valid_results:
        return None

    total_weight = sum(r.weight for r in valid_results)
    if total_weight <= 0:
        return None

    weighted_sum = sum(r.intrinsic_value * r.weight for r in valid_results)
    return weighted_sum / total_weight


# ──────────────────────────────────────────────────────────
# Historical P/E context
# ──────────────────────────────────────────────────────────

def _historical_pe_context(data, cmp, profile):
    """Compute where current P/E sits relative to 5-year historical range.

    Uses EPS series + current CMP to back-calculate approximate historical P/E.
    Returns (pe_current, pe_5yr_avg, pe_5yr_low, pe_5yr_high, position_label).
    """
    pe_current = get_ratio(data, "Stock P/E")
    eps_series = get_eps_series(data, n_years=5)

    if not eps_series or len(eps_series) < 3 or pe_current is None:
        return pe_current, None, None, None, ""

    # Use the sector's typical P/E range as additional context
    sector_pe_low, sector_pe_high = profile.pe_range

    # Estimate historical P/E from EPS trajectory
    # This is approximate — CMP was different each year, but we use
    # the current P/E as anchor and adjust by EPS growth
    current_eps = eps_series[-1] if eps_series[-1] and eps_series[-1] > 0 else None
    if current_eps is None or current_eps <= 0:
        return pe_current, None, None, None, ""

    historical_pes = []
    for eps in eps_series:
        if eps and eps > 0:
            # Implied P/E if stock traded at sector-average multiple
            # Simplified: use ratio of current EPS to historical EPS to approximate P/E change
            implied_pe = pe_current * (current_eps / eps)
            historical_pes.append(implied_pe)

    if len(historical_pes) < 3:
        return pe_current, None, None, None, ""

    pe_avg = sum(historical_pes) / len(historical_pes)
    pe_low = min(historical_pes)
    pe_high = max(historical_pes)

    if pe_current < pe_avg * 0.85:
        position = "Below average"
    elif pe_current > pe_avg * 1.15:
        position = "Above average"
    else:
        position = "Near average"

    return pe_current, round(pe_avg, 1), round(pe_low, 1), round(pe_high, 1), position


# ──────────────────────────────────────────────────────────
# Helper: EPS
# ──────────────────────────────────────────────────────────

def _get_eps(data):
    """Get EPS — prefer Stock P/E and CMP derivation, else from P&L."""
    pe = get_ratio(data, "Stock P/E")
    cmp = get_cmp(data)
    if pe and cmp and pe > 0:
        return cmp / pe

    np_ttm = get_ttm_value(data, "profit_loss", "Net Profit")
    if np_ttm is None:
        np_ttm = get_latest_annual(data, "profit_loss", "Net Profit")
    shares = get_shares_outstanding(data)
    if np_ttm is not None and shares and shares > 0:
        return np_ttm / shares
    return None


def _get_book_value(data):
    """Get book value per share."""
    return get_ratio(data, "Book Value")


def _get_roce(data):
    """Get ROCE as decimal."""
    roce = get_ratio(data, "ROCE")
    if roce is not None:
        return roce / 100 if roce > 1 else roce
    return None


# ──────────────────────────────────────────────────────────
# Method 1: Graham Number
# ──────────────────────────────────────────────────────────

def _graham_number(data, cmp, profile, roe):
    """Graham Number = sqrt(22.5 x EPS x BVPS)."""
    result = ValuationResult(method="Graham Number")
    eps = _get_eps(data)
    bv = _get_book_value(data)

    if eps is None or eps <= 0:
        result.notes = "Negative or missing EPS"
        return result
    if bv is None or bv <= 0:
        result.notes = "Negative or missing Book Value"
        return result

    graham = math.sqrt(22.5 * eps * bv)
    result.intrinsic_value = graham
    result.confidence = "high"
    result.data_quality = "complete"
    result.notes = f"EPS: \u20b9{eps:.2f}, BV: \u20b9{bv:.2f}"
    return result


# ──────────────────────────────────────────────────────────
# Method 2: DCF (Discounted Cash Flow) — uses actual FCF
# ──────────────────────────────────────────────────────────

def _dcf(data, cmp, profile, roe):
    """10-year DCF using actual Free Cash Flow from Screener.in.

    Growth rate = min(FCF CAGR, Revenue CAGR, Profit CAGR) over 5 years.
    This prevents the model from assuming FCF grows faster than the
    underlying business — FCF can be lumpy, but revenue/profit are the
    real growth anchors.

    Base FCF = average of last 3 years (smooths spikes/dips).
    """
    result = ValuationResult(method="DCF")
    discount_rate = profile.discount_rate

    # Use actual FCF (falls back to CFO inside get_fcf_series)
    fcf_series = get_fcf_series(data, n_years=10)

    if not fcf_series or len(fcf_series) < 3:
        result.notes = "Insufficient cash flow data"
        return result

    # ── Growth rate: minimum of FCF, Revenue, and Profit CAGR ────────
    # Use 5-year lookback for growth (not 10) — more representative
    fcf_5y = get_fcf_series(data, n_years=5)
    revenue_5y = get_value_series(data, "profit_loss", "Sales", n_years=5)
    profit_5y = get_value_series(data, "profit_loss", "Net Profit", n_years=5)

    g_fcf = growth_rate(fcf_5y) if fcf_5y and len(fcf_5y) >= 3 else None
    g_rev = growth_rate(revenue_5y) if revenue_5y and len(revenue_5y) >= 3 else None
    g_profit = growth_rate(profit_5y) if profit_5y and len(profit_5y) >= 3 else None

    # Collect all valid positive growth rates
    growth_candidates = [g for g in [g_fcf, g_rev, g_profit] if g is not None and g > 0]

    if not growth_candidates:
        # All negative or unavailable — try the raw FCF CAGR as fallback
        g_fallback = growth_rate(fcf_series)
        if g_fallback is None or g_fallback <= -0.20:
            result.notes = "Negative/declining growth across FCF, revenue, and profit"
            return result
        g = max(g_fallback, 0.02)
        growth_source = "FCF (fallback)"
    else:
        # Conservative anchor: use the minimum
        g = min(growth_candidates)
        growth_source = "min(FCF, Rev, Profit)"

    # Cap and floor
    g = min(g, 0.20)
    g = max(g, 0.02)

    # ── Base FCF: 3-year average (smooths spikes) ────────────────────
    recent_fcf = [v for v in fcf_series[-3:] if v is not None and v > 0]
    if not recent_fcf:
        result.notes = "No positive recent FCF"
        return result
    base_fcf = sum(recent_fcf) / len(recent_fcf)

    shares = get_shares_outstanding(data)
    if shares is None or shares <= 0:
        result.notes = "Cannot determine shares outstanding"
        return result

    r = discount_rate
    tg = TERMINAL_GROWTH_RATE

    pv_fcf = 0
    fcf = base_fcf
    for year in range(1, 11):
        if year <= 5:
            fcf *= (1 + g)
        else:
            fade_g = g - (g - tg) * (year - 5) / 5
            fcf *= (1 + fade_g)
        pv_fcf += fcf / (1 + r) ** year

    terminal_fcf = fcf * (1 + tg)
    tv = terminal_fcf / (r - tg)
    pv_tv = tv / (1 + r) ** 10

    total_value = pv_fcf + pv_tv
    iv_per_share = total_value / shares

    result.intrinsic_value = iv_per_share
    result.confidence = "medium" if len(fcf_series) >= 5 else "low"
    result.data_quality = "complete" if len(fcf_series) >= 5 else "partial"

    growth_detail = []
    if g_fcf is not None:
        growth_detail.append(f"FCF {g_fcf*100:.1f}%")
    if g_rev is not None:
        growth_detail.append(f"Rev {g_rev*100:.1f}%")
    if g_profit is not None:
        growth_detail.append(f"Profit {g_profit*100:.1f}%")
    growth_str = ", ".join(growth_detail)

    result.notes = (f"FCF-based (3yr avg). Used: {g*100:.1f}% = {growth_source} "
                    f"[{growth_str}]. Disc: {r*100:.0f}%, Terminal: {tg*100:.0f}%")
    return result


# ──────────────────────────────────────────────────────────
# Method 3: PEG-Based Valuation — quality-adjusted
# ──────────────────────────────────────────────────────────

def _peg_valuation(data, cmp, profile, roe):
    """Fair P/E from growth rate, with quality-adjusted floor from sector profile."""
    result = ValuationResult(method="PEG Ratio")
    eps = _get_eps(data)
    if eps is None or eps <= 0:
        result.notes = "No positive EPS"
        return result

    np_series = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    g = growth_rate(np_series)
    if g is None or g <= 0:
        result.notes = "Non-positive earnings growth"
        return result

    # Quality-adjusted P/E floor
    pe_floor = get_quality_adjusted_peg_floor(profile, roe)
    pe_ceiling = profile.peg_pe_ceiling

    fair_pe = min(g * 100, pe_ceiling)
    fair_pe = max(fair_pe, pe_floor)

    result.intrinsic_value = fair_pe * eps
    result.confidence = "medium"
    result.data_quality = "complete" if len(np_series) >= 5 else "partial"
    result.notes = (f"Earnings CAGR: {g*100:.1f}%, Fair P/E: {fair_pe:.1f}x "
                    f"(floor {pe_floor}x), EPS: \u20b9{eps:.2f}")
    return result


# ──────────────────────────────────────────────────────────
# Method 4: EV/EBITDA — sector-specific multiples
# ──────────────────────────────────────────────────────────

def _ev_ebitda(data, cmp, profile, roe):
    """Fair EV using sector-appropriate EV/EBITDA multiple."""
    result = ValuationResult(method="EV/EBITDA")

    op_profit = get_ttm_value(data, "profit_loss", "Operating Profit")
    if op_profit is None:
        op_profit = get_latest_annual(data, "profit_loss", "Operating Profit")
    depreciation = get_ttm_value(data, "profit_loss", "Depreciation")
    if depreciation is None:
        depreciation = get_latest_annual(data, "profit_loss", "Depreciation")
    if depreciation is None:
        depreciation = 0

    if op_profit is None:
        result.notes = "No operating profit data"
        return result

    ebitda = op_profit + abs(depreciation) if depreciation else op_profit

    mcap = get_ratio(data, "Market Cap")
    borrowings = get_latest_annual(data, "balance_sheet", "Borrowings")
    if borrowings is None:
        borrowings = 0
    cash = get_latest_annual(data, "balance_sheet", "Cash Equivalents")
    if cash is None:
        cash = get_latest_annual(data, "balance_sheet", "Investments")
        if cash is None:
            cash = 0

    net_debt = (borrowings or 0) - (cash or 0)
    if mcap is None:
        result.notes = "No market cap"
        return result

    if ebitda <= 0:
        result.notes = "Non-positive EBITDA"
        return result

    # Sector-specific fair multiple
    ev_low, ev_high = profile.ev_ebitda_range
    roce = _get_roce(data)

    # Within the sector range, position based on ROCE quality
    if roce and roce > 0.20:
        fair_multiple = ev_high
    elif roce and roce > 0.12:
        fair_multiple = (ev_low + ev_high) / 2
    else:
        fair_multiple = ev_low

    fair_ev = fair_multiple * ebitda
    fair_equity = fair_ev - net_debt
    shares = get_shares_outstanding(data)
    if shares and shares > 0:
        result.intrinsic_value = fair_equity / shares
        result.confidence = "medium"
        result.data_quality = "partial"
        result.notes = (f"EBITDA: \u20b9{ebitda:.0f}Cr, Fair EV/EBITDA: {fair_multiple:.0f}x "
                        f"(sector range {ev_low}-{ev_high}x), Net Debt: \u20b9{net_debt:.0f}Cr")
    return result


# ──────────────────────────────────────────────────────────
# Method 5: Earnings Power Value (EPV)
# ──────────────────────────────────────────────────────────

def _epv(data, cmp, profile, roe):
    """EPV = Normalized earnings / WACC. Zero-growth valuation."""
    result = ValuationResult(method="Earnings Power Value")
    discount_rate = profile.discount_rate

    np_series = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    if not np_series or len(np_series) < 3:
        result.notes = "Insufficient profit data"
        return result

    avg_profit = mean(np_series)
    if avg_profit is None or avg_profit <= 0:
        result.notes = "Negative average earnings"
        return result

    shares = get_shares_outstanding(data)
    if shares is None or shares <= 0:
        result.notes = "Cannot determine shares"
        return result

    epv_total = avg_profit / discount_rate
    epv_per_share = epv_total / shares

    result.intrinsic_value = epv_per_share
    result.confidence = "medium"
    result.data_quality = "complete" if len(np_series) >= 5 else "partial"
    result.notes = (f"Avg Profit: \u20b9{avg_profit:.0f}Cr, "
                    f"Discount: {discount_rate*100:.0f}%, Zero-growth floor")
    return result


# ══════════════════════════════════════════════════════════
# BANK / FINANCIAL SERVICES — Specialised methods
# ══════════════════════════════════════════════════════════
#
# Standard methods fail for banks because:
#   - "Debt" is actually deposits (the raw material)
#   - FCF is meaningless (cash flows are the business)
#   - EBITDA doesn't exist for banks
#   - Book value IS the anchor asset (unlike tech/FMCG)
#
# These 5 methods are all P/B-anchored, appropriate for
# leverage-driven businesses: banks, NBFCs, housing finance,
# insurance.
# ══════════════════════════════════════════════════════════


def _bank_cost_of_equity(profile, data):
    """Cost of equity for banks. PSU banks get a governance premium."""
    coe = profile.discount_rate  # base: 12% for Financial Services
    promoter = get_promoter_holding(data)
    if promoter and promoter > 50:
        coe += 0.015  # +1.5% for PSU banks (governance / efficiency risk)
    return coe


def _bank_sustainable_growth(data):
    """Sustainable growth rate for banks.

    Uses min(book value CAGR, profit CAGR) over 5 years as the anchor.
    This prevents overstating growth from cyclical profit recovery.
    """
    # Book value growth (Reserves proxy)
    reserves = get_value_series(data, "balance_sheet", "Reserves", n_years=5)
    g_bv = growth_rate(reserves) if reserves and len(reserves) >= 3 else None

    # Profit growth
    profits = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    g_profit = growth_rate(profits) if profits and len(profits) >= 3 else None

    candidates = [g for g in [g_bv, g_profit] if g is not None and g > 0]
    if not candidates:
        return 0.04  # floor: 4% nominal GDP growth

    return min(candidates)


def _bank_gordon_pb(data, cmp, profile, roe):
    """Gordon Growth P/B: Fair P/B = (ROE - g) / (CoE - g).

    THE primary valuation method for banks. A bank generating ROE > CoE
    deserves P/B > 1; a bank with ROE < CoE deserves P/B < 1.
    """
    result = ValuationResult(method="Gordon Growth P/B")
    bv = _get_book_value(data)
    if bv is None or bv <= 0:
        result.notes = "No book value"
        return result

    roe_dec = roe / 100 if roe and roe > 1 else (roe or 0)
    if roe_dec <= 0:
        result.notes = "Negative ROE"
        return result

    coe = _bank_cost_of_equity(profile, data)
    g = _bank_sustainable_growth(data)

    # Cap growth: min 3% spread vs CoE, max 10% absolute
    g = min(g, coe - 0.03, 0.10)
    g = max(g, 0.02)

    fair_pb = (roe_dec - g) / (coe - g)
    # Floor: even a bad bank has some franchise value
    fair_pb = max(fair_pb, 0.3)
    # Cap: even the best bank rarely sustains > 5x P/B
    fair_pb = min(fair_pb, 5.0)

    iv = fair_pb * bv
    result.intrinsic_value = iv
    result.confidence = "high"
    result.data_quality = "complete"
    result.notes = (f"ROE: {roe_dec*100:.1f}%, CoE: {coe*100:.1f}%, "
                    f"g: {g*100:.1f}%, Fair P/B: {fair_pb:.2f}x, "
                    f"BV: \u20b9{bv:.0f}")
    return result


def _bank_justified_pe(data, cmp, profile, roe):
    """Justified P/E = Fair P/B / ROE.

    Derived from Gordon Growth: if Fair P/B = (ROE-g)/(CoE-g),
    then Fair P/E = Fair P/B / ROE = (ROE-g) / [ROE × (CoE-g)].
    """
    result = ValuationResult(method="Justified P/E")
    eps = _get_eps(data)
    if eps is None or eps <= 0:
        result.notes = "No positive EPS"
        return result

    roe_dec = roe / 100 if roe and roe > 1 else (roe or 0)
    if roe_dec <= 0.02:
        result.notes = "ROE too low for meaningful P/E"
        return result

    coe = _bank_cost_of_equity(profile, data)
    g = _bank_sustainable_growth(data)
    g = min(g, coe - 0.03, 0.10)
    g = max(g, 0.02)

    fair_pb = (roe_dec - g) / (coe - g)
    fair_pb = max(fair_pb, 0.3)
    fair_pb = min(fair_pb, 5.0)

    fair_pe = fair_pb / roe_dec
    # Sanity bounds
    fair_pe = max(fair_pe, 3.0)
    fair_pe = min(fair_pe, 25.0)

    iv = fair_pe * eps
    result.intrinsic_value = iv
    result.confidence = "high"
    result.data_quality = "complete"
    result.notes = (f"Fair P/E: {fair_pe:.1f}x (from P/B {fair_pb:.2f}x / "
                    f"ROE {roe_dec*100:.1f}%), EPS: \u20b9{eps:.2f}")
    return result


def _bank_ddm(data, cmp, profile, roe):
    """Dividend Discount Model: Fair Value = DPS₁ / (CoE - g).

    Banks are reliable dividend payers. DDM works well for mature banks.
    """
    result = ValuationResult(method="Dividend Discount")
    div_yield = get_ratio(data, "Dividend Yield")
    if div_yield is None or div_yield <= 0:
        result.notes = "No dividend data"
        return result

    # Current DPS from yield
    dps = cmp * div_yield / 100

    coe = _bank_cost_of_equity(profile, data)
    g = _bank_sustainable_growth(data)
    g = min(g, coe - 0.03, 0.10)
    g = max(g, 0.02)

    # Next year's dividend
    dps_next = dps * (1 + g)

    if coe <= g:
        result.notes = "Growth exceeds cost of equity"
        return result

    iv = dps_next / (coe - g)
    result.intrinsic_value = iv
    result.confidence = "medium"
    result.data_quality = "complete"
    result.notes = (f"DPS: \u20b9{dps:.2f}, Yield: {div_yield:.1f}%, "
                    f"g: {g*100:.1f}%, CoE: {coe*100:.1f}%")
    return result


def _bank_residual_income(data, cmp, profile, roe):
    """Residual Income: BV × [1 + (ROE - CoE) / (CoE - g)].

    Values the bank as book value plus the present value of future
    excess returns (returns above cost of equity).
    """
    result = ValuationResult(method="Residual Income")
    bv = _get_book_value(data)
    if bv is None or bv <= 0:
        result.notes = "No book value"
        return result

    roe_dec = roe / 100 if roe and roe > 1 else (roe or 0)
    if roe_dec <= 0:
        result.notes = "Negative ROE"
        return result

    coe = _bank_cost_of_equity(profile, data)
    g = _bank_sustainable_growth(data)
    g = min(g, coe - 0.03, 0.10)
    g = max(g, 0.02)

    excess_return = roe_dec - coe
    multiplier = 1 + excess_return / (coe - g)
    # Floor at 0.3 (even value-destroying banks have some liquidation value)
    multiplier = max(multiplier, 0.3)
    multiplier = min(multiplier, 5.0)

    iv = bv * multiplier
    result.intrinsic_value = iv
    result.confidence = "medium"
    result.data_quality = "complete"
    excess_label = f"+{excess_return*100:.1f}%" if excess_return > 0 else f"{excess_return*100:.1f}%"
    result.notes = (f"BV: \u20b9{bv:.0f}, ROE-CoE: {excess_label}, "
                    f"Multiplier: {multiplier:.2f}x")
    return result


def _bank_pb_reversion(data, cmp, profile, roe):
    """P/B Mean Reversion: back-calculate historical P/B from BV series.

    Uses the EPS-implied P/E history and ROE to estimate historical P/B,
    then applies the average to current BV.
    """
    result = ValuationResult(method="P/B Mean Reversion")
    bv = _get_book_value(data)
    if bv is None or bv <= 0:
        result.notes = "No book value"
        return result

    # Current P/B
    pb_current = get_pb_ratio(data)
    if pb_current is None:
        result.notes = "Cannot compute current P/B"
        return result

    # Estimate historical P/B from EPS and BV series
    eps_series = get_eps_series(data, n_years=5)
    reserves_series = get_value_series(data, "balance_sheet", "Reserves", n_years=5)
    eq_cap_series = get_value_series(data, "balance_sheet", "Equity Capital", n_years=5)

    if (not eps_series or len(eps_series) < 3 or
            not reserves_series or len(reserves_series) < 3):
        # Fallback: use sector-average P/B
        roe_dec = roe / 100 if roe and roe > 1 else (roe or 0.10)
        coe = _bank_cost_of_equity(profile, data)
        # Reasonable avg P/B for Indian banks: ~1.2x
        avg_pb = max(1.0, min(roe_dec / coe, 2.5))
        iv = avg_pb * bv
        result.intrinsic_value = iv
        result.confidence = "low"
        result.data_quality = "partial"
        result.notes = (f"Limited history. Sector avg P/B: {avg_pb:.2f}x, "
                        f"BV: \u20b9{bv:.0f}")
        return result

    # Back-calculate implied P/B from P/E and ROE per year
    shares = get_shares_outstanding(data)
    if shares is None or shares <= 0:
        result.notes = "Cannot determine shares"
        return result

    historical_pbs = []
    n = min(len(eps_series), len(reserves_series))
    for i in range(n):
        eps_i = eps_series[i]
        eq_cap_i = eq_cap_series[i] if eq_cap_series and i < len(eq_cap_series) else 0
        res_i = reserves_series[i]
        if eps_i and eps_i > 0 and res_i and res_i > 0:
            bv_i = (eq_cap_i + res_i) / shares if shares > 0 else 0
            if bv_i > 0:
                # Implied P/B = (Current P/B) × (current BV / historical BV)
                # This approximates where the stock traded relative to book
                implied_pb = pb_current * (bv / bv_i)
                historical_pbs.append(implied_pb)

    if len(historical_pbs) < 3:
        result.notes = "Insufficient history for P/B reversion"
        return result

    avg_pb = sum(historical_pbs) / len(historical_pbs)
    avg_pb = max(avg_pb, 0.3)
    avg_pb = min(avg_pb, 5.0)

    iv = avg_pb * bv
    result.intrinsic_value = iv
    result.confidence = "medium"
    result.data_quality = "complete"
    result.notes = (f"5Y Avg P/B: {avg_pb:.2f}x (range {min(historical_pbs):.2f}x\u2013"
                    f"{max(historical_pbs):.2f}x), Current: {pb_current:.2f}x, "
                    f"BV: \u20b9{bv:.0f}")
    return result
