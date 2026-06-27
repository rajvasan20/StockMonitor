"""Thesis Data Cruncher — deterministic computation of all financial metrics.

Takes Screener.in parsed data + valuation summary and produces structured
metrics for every module of the thesis report. Pure math — no AI.
"""

from shared.data_parser import (
    get_annual_values, get_value_series, get_cmp, get_ratio,
    get_shares_outstanding, get_latest_annual, get_ttm_value,
    get_fcf_series, get_eps_series, get_debt_to_equity,
    get_pb_ratio, get_promoter_holding, get_avg_roce, get_avg_roe,
)
from shared.utils import growth_rate, cagr, mean


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fy(year_str):
    """'Mar 2016' → 'FY16'."""
    parts = year_str.strip().split()
    if len(parts) >= 2:
        try:
            return f"FY{int(parts[-1]) % 100:02d}"
        except ValueError:
            pass
    return year_str


def _qlabel(year_str):
    """'Sep 2023' → "Sep'23"."""
    parts = year_str.strip().split()
    if len(parts) >= 2:
        try:
            return f"{parts[0]}'{int(parts[-1]) % 100:02d}"
        except ValueError:
            pass
    return year_str


def _rows(data, section):
    """(year_str, index) pairs for a section, excluding TTM."""
    sec = data.get(section, {})
    years = sec.get("years", [])
    return [(y, i) for i, y in enumerate(years) if y.upper() != "TTM"]


def _v(data, section, metric, idx):
    """Value at index from section data."""
    vals = data.get(section, {}).get("data", {}).get(metric, [])
    return vals[idx] if idx < len(vals) else None


def _pick(data, section, idx, *names):
    """Try multiple metric names, return first non-None."""
    for name in names:
        val = _v(data, section, name, idx)
        if val is not None:
            return val
    return None


def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pct_change(new, old):
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100


# ── Main ─────────────────────────────────────────────────────────────────────

def crunch_all(data, valuation_summary):
    """Compute all thesis metrics. Returns dict."""
    cmp = get_cmp(data)
    mcap = get_ratio(data, "Market Cap")
    pe = get_ratio(data, "Stock P/E")
    shares = get_shares_outstanding(data)
    eps = _safe_div(cmp, pe)

    borrowings_latest = get_latest_annual(data, "balance_sheet", "Borrowings") or 0
    cash_latest = get_latest_annual(data, "balance_sheet", "Cash Equivalents") or 0
    net_debt = borrowings_latest - cash_latest
    ev = (mcap or 0) + net_debt

    snapshot = {
        "cmp": cmp, "market_cap": mcap, "ev": ev, "eps": eps,
        "shares": shares, "pe": pe,
        "face_value": get_ratio(data, "Face Value"),
        "roe": get_ratio(data, "ROE"),
        "roce": get_ratio(data, "ROCE"),
        "de": get_debt_to_equity(data) or get_ratio(data, "Debt to equity"),
        "pb": get_pb_ratio(data),
        "dividend_yield": get_ratio(data, "Dividend Yield"),
        "book_value": get_ratio(data, "Book Value"),
        "promoter_holding": get_promoter_holding(data),
    }

    # ── Annual P&L ────────────────────────────────────────────
    pl_items = _rows(data, "profit_loss")
    annual_pl = []
    for ys, idx in pl_items:
        row = {"year": _fy(ys)}
        row["sales"] = _v(data, "profit_loss", "Sales", idx)
        row["operating_profit"] = _v(data, "profit_loss", "Operating Profit", idx)
        row["opm_pct"] = _v(data, "profit_loss", "OPM %", idx)
        row["other_income"] = _v(data, "profit_loss", "Other Income", idx)
        row["interest"] = _pick(data, "profit_loss", idx, "Interest", "Finance Costs")
        row["depreciation"] = _v(data, "profit_loss", "Depreciation", idx)
        row["pbt"] = _v(data, "profit_loss", "Profit before tax", idx)
        row["tax_pct"] = _v(data, "profit_loss", "Tax %", idx)
        row["pat"] = _v(data, "profit_loss", "Net Profit", idx)
        row["eps"] = _v(data, "profit_loss", "EPS in Rs", idx)
        row["dividend_payout"] = _v(data, "profit_loss", "Dividend Payout %", idx)
        annual_pl.append(row)

    # ── Annual Balance Sheet ──────────────────────────────────
    bs_items = _rows(data, "balance_sheet")
    annual_bs = []
    for ys, idx in bs_items:
        row = {"year": _fy(ys)}
        row["equity_capital"] = _pick(data, "balance_sheet", idx,
                                      "Equity Capital", "Share Capital",
                                      "Equity Share Capital")
        row["reserves"] = _v(data, "balance_sheet", "Reserves", idx)
        row["borrowings"] = _v(data, "balance_sheet", "Borrowings", idx)
        row["other_liabilities"] = _v(data, "balance_sheet", "Other Liabilities", idx)
        row["net_block"] = _pick(data, "balance_sheet", idx,
                                 "Fixed Assets", "Net Block",
                                 "Property, Plant and Equipment")
        row["cwip"] = _v(data, "balance_sheet", "CWIP", idx)
        row["investments"] = _v(data, "balance_sheet", "Investments", idx)
        row["other_assets"] = _v(data, "balance_sheet", "Other Assets", idx)
        eq_cap = row["equity_capital"] or 0
        res = row["reserves"] or 0
        row["total_equity"] = (eq_cap + res) if (eq_cap + res) > 0 else None
        annual_bs.append(row)

    # ── Annual Cash Flow ──────────────────────────────────────
    cf_items = _rows(data, "cash_flow")
    annual_cf = []
    for ys, idx in cf_items:
        row = {"year": _fy(ys)}
        row["cfo"] = _v(data, "cash_flow", "Cash from Operating Activity", idx)
        row["cfi"] = _v(data, "cash_flow", "Cash from Investing Activity", idx)
        row["cff"] = _v(data, "cash_flow", "Cash from Financing Activity", idx)
        row["fcf"] = _v(data, "cash_flow", "Free Cash Flow", idx)
        if row["fcf"] is None and row["cfo"] is not None and row["cfi"] is not None:
            row["fcf"] = row["cfo"] + row["cfi"]
        annual_cf.append(row)

    # ── Quarterly P&L ─────────────────────────────────────────
    q_items = _rows(data, "quarters")
    quarterly = []
    for ys, idx in q_items[-10:]:
        row = {"quarter": _qlabel(ys)}
        row["sales"] = _v(data, "quarters", "Sales", idx)
        row["expenses"] = _v(data, "quarters", "Expenses", idx)
        row["operating_profit"] = _v(data, "quarters", "Operating Profit", idx)
        row["opm_pct"] = _v(data, "quarters", "OPM %", idx)
        row["pat"] = _v(data, "quarters", "Net Profit", idx)
        row["pat_margin"] = round(_safe_div(row["pat"], row["sales"]) * 100, 1) \
            if row["pat"] is not None and row["sales"] and row["sales"] > 0 else None
        quarterly.append(row)

    # ── DuPont ROCE Decomposition ─────────────────────────────
    pl_map = {r["year"]: r for r in annual_pl}
    bs_map = {r["year"]: r for r in annual_bs}
    common = [y for y in pl_map if y in bs_map]

    dupont = []
    for year in common:
        pl = pl_map[year]
        bs = bs_map[year]
        ebit = pl.get("operating_profit")
        sales = pl.get("sales")
        total_eq = bs.get("total_equity") or 0
        borr = bs.get("borrowings") or 0
        cap_emp = total_eq + borr
        net_blk = bs.get("net_block")

        roce = _safe_div(ebit, cap_emp)
        ebit_mgn = _safe_div(ebit, sales)
        asset_turn = _safe_div(sales, cap_emp)
        de = _safe_div(borr, total_eq)
        nfa_turn = _safe_div(sales, net_blk)

        dupont.append({
            "year": year,
            "ebit": ebit,
            "cap_employed": cap_emp if cap_emp > 0 else None,
            "roce_pct": round(roce * 100, 1) if roce is not None else None,
            "ebit_margin_pct": round(ebit_mgn * 100, 1) if ebit_mgn is not None else None,
            "asset_turnover": round(asset_turn, 2) if asset_turn is not None else None,
            "de_ratio": round(de, 2) if de is not None else None,
            "nfa_turnover": round(nfa_turn, 1) if nfa_turn is not None else None,
        })

    # ── Revenue Quality ───────────────────────────────────────
    dd_rows = _rows(data, "ratios")
    dd_map = {}
    for ys, idx in dd_rows:
        v = _v(data, "ratios", "Debtor Days", idx)
        if v is not None:
            dd_map[_fy(ys)] = v

    revenue_quality = []
    for i, row in enumerate(annual_pl):
        rq = {"year": row["year"]}
        sales = row.get("sales")
        prev_sales = annual_pl[i - 1].get("sales") if i > 0 else None
        rq["sales_growth"] = round(_pct_change(sales, prev_sales), 1) \
            if i > 0 and sales is not None and prev_sales else None
        rq["debtor_days"] = dd_map.get(row["year"])
        revenue_quality.append(rq)

    # ── Cash Flow Quality ─────────────────────────────────────
    cf_map = {r["year"]: r for r in annual_cf}
    cashflow_quality = []
    cum_cfo, cum_pat = 0.0, 0.0

    for pl_row in annual_pl:
        year = pl_row["year"]
        cf = cf_map.get(year, {})
        pat = pl_row.get("pat")
        cfo = cf.get("cfo")
        fcf = cf.get("fcf")
        op = pl_row.get("operating_profit")
        dep = pl_row.get("depreciation")
        ebitda = (op or 0) + abs(dep or 0) if op is not None else None

        cfo_pat = _safe_div(cfo, pat) if pat and pat > 0 else None
        cfo_ebitda = _safe_div(cfo, ebitda) if ebitda and ebitda > 0 else None
        fcf_pat = _safe_div(fcf, pat) if pat and pat > 0 else None

        if cfo is not None:
            cum_cfo += cfo
        if pat is not None and pat > 0:
            cum_pat += pat

        cashflow_quality.append({
            "year": year,
            "pat": pat, "cfo": cfo, "ebitda": ebitda,
            "cfo_pat": round(cfo_pat, 2) if cfo_pat is not None else None,
            "cfo_ebitda": round(cfo_ebitda, 2) if cfo_ebitda is not None else None,
            "fcf": fcf,
            "fcf_pat": round(fcf_pat, 2) if fcf_pat is not None else None,
        })

    cum_cfo_pat = round(_safe_div(cum_cfo, cum_pat), 2) if cum_pat > 0 else None

    # Latest FCF for yield calc
    latest_fcf = None
    for cf_row in reversed(annual_cf):
        if cf_row.get("fcf") is not None:
            latest_fcf = cf_row["fcf"]
            break
    fcf_yield = round(_safe_div(latest_fcf, mcap) * 100, 2) \
        if latest_fcf and mcap and mcap > 0 else None

    # ── Key Aggregates ────────────────────────────────────────
    sales_5y = get_value_series(data, "profit_loss", "Sales", n_years=5)
    profit_5y = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    fcf_5y = get_fcf_series(data, n_years=5)

    key_ratios = {
        "sales_cagr_5y": growth_rate(sales_5y) if sales_5y and len(sales_5y) >= 3 else None,
        "profit_cagr_5y": growth_rate(profit_5y) if profit_5y and len(profit_5y) >= 3 else None,
        "fcf_cagr_5y": growth_rate(fcf_5y) if fcf_5y and len(fcf_5y) >= 3 else None,
        "avg_roce_5y": get_avg_roce(data, 5),
        "avg_roe_5y": get_avg_roe(data, 5),
        "cumulative_cfo": cum_cfo,
        "cumulative_pat": cum_pat,
        "cumulative_cfo_pat": cum_cfo_pat,
        "fcf_yield": fcf_yield,
    }

    # ── Valuation Multiples ───────────────────────────────────
    latest_ebitda = None
    for pl_row in reversed(annual_pl):
        op = pl_row.get("operating_profit")
        dep = pl_row.get("depreciation")
        if op is not None:
            latest_ebitda = op + abs(dep or 0)
            break

    ev_ebitda = _safe_div(ev, latest_ebitda) if latest_ebitda and latest_ebitda > 0 else None
    p_fcf = _safe_div(mcap, latest_fcf) if latest_fcf and latest_fcf > 0 else None
    latest_sales = get_latest_annual(data, "profit_loss", "Sales")
    p_sales = _safe_div(mcap, latest_sales) if latest_sales and latest_sales > 0 else None

    valuation_multiples = {
        "pe": pe,
        "ev_ebitda": round(ev_ebitda, 1) if ev_ebitda else None,
        "p_fcf": round(p_fcf, 1) if p_fcf else None,
        "p_sales": round(p_sales, 2) if p_sales else None,
        "pb": round(get_pb_ratio(data), 1) if get_pb_ratio(data) else None,
        "fcf_yield": fcf_yield,
    }

    return {
        "snapshot": snapshot,
        "annual_pl": annual_pl,
        "annual_bs": annual_bs,
        "annual_cf": annual_cf,
        "quarterly": quarterly,
        "dupont": dupont,
        "revenue_quality": revenue_quality,
        "cashflow_quality": cashflow_quality,
        "key_ratios": key_ratios,
        "valuation_multiples": valuation_multiples,
    }
