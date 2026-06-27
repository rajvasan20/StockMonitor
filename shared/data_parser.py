"""Parse Screener.in HTML into structured financial data."""

from bs4 import BeautifulSoup
from shared.utils import safe_float, logger


def parse_company_page(html, ticker):
    """Parse full Screener.in company page into structured dict.

    Returns dict with keys:
        ticker, name, sector, industry, top_ratios, profit_loss,
        balance_sheet, cash_flow, ratios, quarters, shareholding
    """
    soup = BeautifulSoup(html, "lxml")
    sector, industry = _parse_sector(soup)
    data = {
        "ticker": ticker,
        "name": _parse_company_name(soup),
        "sector": sector,
        "industry": industry,
        "top_ratios": _parse_top_ratios(soup),
        "profit_loss": _parse_section_table(soup, "profit-loss"),
        "balance_sheet": _parse_section_table(soup, "balance-sheet"),
        "cash_flow": _parse_section_table(soup, "cash-flow"),
        "ratios": _parse_section_table(soup, "ratios"),
        "quarters": _parse_section_table(soup, "quarters"),
        "shareholding": _parse_section_table(soup, "shareholding"),
    }
    return data


def _parse_sector(soup):
    """Extract sector and industry from peers section links.

    Screener.in peers section has links like:
        /market/IN08/              → "Information Technology" (sector)
        /market/IN08/IN0801/       → "IT - Software" (industry)

    Returns (sector, industry) — both may be None.
    """
    peers = soup.find("section", id="peers")
    if not peers:
        return None, None

    sector = None
    industry = None
    for a in peers.find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not href.startswith("/market/") or not text:
            continue
        # Count path depth: /market/XX/ = sector, /market/XX/YY/ = industry
        parts = [p for p in href.strip("/").split("/") if p and p != "market"]
        if len(parts) == 1 and sector is None:
            sector = text
        elif len(parts) == 2 and industry is None:
            industry = text
        if sector and industry:
            break

    return sector, industry


def _parse_company_name(soup):
    """Extract company name from page title."""
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    title = soup.find("title")
    if title:
        text = title.get_text(strip=True)
        if " - " in text:
            return text.split(" - ")[1].strip()
        return text
    return None


def _parse_top_ratios(soup):
    """Parse the top ratios section (Market Cap, P/E, Book Value, etc.)."""
    ratios = {}
    top_div = soup.find("div", id="top")
    if not top_div:
        top_div = soup.find("ul", id="top-ratios")
    if not top_div:
        logger.warning("Could not find top ratios section")
        return ratios

    for li in top_div.find_all("li"):
        spans = li.find_all("span")
        if len(spans) >= 2:
            name = spans[0].get_text(strip=True).rstrip(":")
            value = spans[-1].get_text(strip=True)
            ratios[name] = value

    return ratios


def _parse_section_table(soup, section_id):
    """Parse a financial table from a section.

    Returns dict:
        {
            "years": ["Mar 2015", "Mar 2016", ..., "TTM"],
            "data": {
                "Sales": [val1, val2, ...],
                "Operating Profit": [...],
                ...
            }
        }
    """
    section = soup.find("section", id=section_id)
    if not section:
        return {"years": [], "data": {}}

    table = section.find("table")
    if not table:
        return {"years": [], "data": {}}

    rows = table.find_all("tr")
    if not rows:
        return {"years": [], "data": {}}

    # First row = year headers
    header_cells = rows[0].find_all(["th", "td"])
    years = []
    for cell in header_cells[1:]:
        text = cell.get_text(strip=True)
        if text:
            years.append(text)

    # Data rows
    data = {}
    for row in rows[1:]:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        metric_cell = cells[0]
        metric_name = metric_cell.get_text(strip=True).rstrip("+")
        if not metric_name:
            continue

        values = []
        for cell in cells[1:]:
            text = cell.get_text(strip=True)
            values.append(safe_float(text))

        while len(values) < len(years):
            values.append(None)
        values = values[:len(years)]

        data[metric_name] = values

    return {"years": years, "data": data}


# ── Accessor helpers ─────────────────────────────────────────────────────────

def get_ratio(data, name):
    """Get a single ratio value from top_ratios. Returns float or None."""
    val = data.get("top_ratios", {}).get(name)
    return safe_float(val)


def get_annual_values(data, section, metric, exclude_ttm=True):
    """Get list of annual values for a metric from a section."""
    sec = data.get(section, {})
    years = sec.get("years", [])
    values = sec.get("data", {}).get(metric, [])

    pairs = list(zip(years, values))
    if exclude_ttm:
        pairs = [(y, v) for y, v in pairs if y.upper() != "TTM"]

    return pairs


def get_latest_annual(data, section, metric):
    """Get the most recent annual (non-TTM) value."""
    pairs = get_annual_values(data, section, metric, exclude_ttm=True)
    if not pairs:
        return None
    return pairs[-1][1]


def get_ttm_value(data, section, metric):
    """Get the TTM value for a metric."""
    sec = data.get(section, {})
    years = sec.get("years", [])
    values = sec.get("data", {}).get(metric, [])
    for y, v in zip(years, values):
        if y.upper() == "TTM":
            return v
    return None


def get_value_series(data, section, metric, n_years=None, exclude_ttm=True):
    """Get a list of float values for a metric (oldest to newest)."""
    pairs = get_annual_values(data, section, metric, exclude_ttm=exclude_ttm)
    values = [v for _, v in pairs if v is not None]
    if n_years and len(values) > n_years:
        values = values[-n_years:]
    return values


def get_shares_outstanding(data):
    """Estimate shares outstanding from Market Cap and CMP."""
    mcap = get_ratio(data, "Market Cap")
    cmp = get_ratio(data, "Current Price")
    if mcap and cmp and cmp > 0:
        return mcap / cmp
    return None


def get_cmp(data):
    """Get current market price."""
    return get_ratio(data, "Current Price")


def get_debt_to_equity(data):
    """Compute D/E from balance sheet."""
    borrowings = get_latest_annual(data, "balance_sheet", "Borrowings")
    equity = get_latest_annual(data, "balance_sheet", "Equity Capital")
    reserves = get_latest_annual(data, "balance_sheet", "Reserves")
    if borrowings is not None and equity is not None and reserves is not None:
        shareholder_equity = equity + reserves
        if shareholder_equity > 0:
            return borrowings / shareholder_equity
    return None


def get_avg_roce(data, n_years=5):
    """Get N-year average ROCE from ratios section."""
    roce_series = get_value_series(data, "ratios", "ROCE %", n_years=n_years)
    if roce_series:
        clean = [v for v in roce_series if v is not None]
        if clean:
            return sum(clean) / len(clean)
    return None


def get_fcf_series(data, n_years=None):
    """Get Free Cash Flow series. Falls back to CFO if FCF not available."""
    fcf = get_value_series(data, "cash_flow", "Free Cash Flow", n_years=n_years)
    if fcf and len(fcf) >= 2:
        return fcf
    return get_value_series(data, "cash_flow", "Cash from Operating Activity", n_years=n_years)


def get_promoter_holding(data):
    """Get latest promoter holding % from shareholding section."""
    series = get_value_series(data, "shareholding", "Promoters")
    if series:
        return series[-1]
    return None


def get_promoter_holding_series(data, n_quarters=None):
    """Get promoter holding % series for trend analysis."""
    return get_value_series(data, "shareholding", "Promoters", n_years=n_quarters)


def get_pb_ratio(data):
    """Compute P/B ratio from CMP and Book Value."""
    cmp = get_cmp(data)
    bv = get_ratio(data, "Book Value")
    if cmp and bv and bv > 0:
        return cmp / bv
    return None


def get_debtor_days_series(data, n_years=None):
    """Get debtor days series from ratios section."""
    return get_value_series(data, "ratios", "Debtor Days", n_years=n_years)


def get_eps_series(data, n_years=None):
    """Get EPS series from P&L."""
    return get_value_series(data, "profit_loss", "EPS in Rs", n_years=n_years)


def get_avg_roe(data, n_years=5):
    """Compute N-year average ROE from P&L and Balance Sheet."""
    np_pairs = get_annual_values(data, "profit_loss", "Net Profit", exclude_ttm=True)
    eq_pairs = get_annual_values(data, "balance_sheet", "Equity Capital", exclude_ttm=True)
    res_pairs = get_annual_values(data, "balance_sheet", "Reserves", exclude_ttm=True)

    if not np_pairs or not eq_pairs or not res_pairs:
        return None

    np_dict = {y: v for y, v in np_pairs if v is not None}
    eq_dict = {y: v for y, v in eq_pairs if v is not None}
    res_dict = {y: v for y, v in res_pairs if v is not None}

    common_years = sorted(set(np_dict.keys()) & set(eq_dict.keys()) & set(res_dict.keys()))
    if n_years and len(common_years) > n_years:
        common_years = common_years[-n_years:]

    roes = []
    for y in common_years:
        se = eq_dict[y] + res_dict[y]
        if se > 0:
            roes.append(np_dict[y] / se * 100)

    if roes:
        return sum(roes) / len(roes)
    return None
