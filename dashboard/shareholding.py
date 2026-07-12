"""FII/DII Shareholding Dashboard — fetch, cache, and render.

Fetches shareholding data (FII, DII, Promoters, Public) for Nifty 500
companies from screener.in, caches per-ticker JSON, and generates a
self-contained HTML dashboard with QoQ (12 quarters) and YoY (5 years) views.

Usage:
    python run.py shareholding-fetch [--test TCS,RELIANCE] [--force]
    python run.py shareholding-dashboard [--output DIR]
"""

import os
import json
from datetime import datetime

from config import SHAREHOLDING_DIR
from shared.scraper import ScreenerScraper
from shared.data_parser import parse_company_page
from shared.ticker_manager import get_nifty500_list
from shared.utils import logger

INDEX_FILE = os.path.join(SHAREHOLDING_DIR, "_index.json")


# ── Fetcher ──────────────────────────────────────────────────────────────────

def fetch_shareholding_data(tickers=None, force=False):
    """Fetch shareholding data for Nifty 500 (or given tickers).

    Saves per-ticker JSON to data/shareholding/TICKER.json.
    Supports resume: skips tickers already cached unless force=True.

    Returns dict with success/skipped/failed/total counts.
    """
    os.makedirs(SHAREHOLDING_DIR, exist_ok=True)

    if tickers is None:
        tickers = get_nifty500_list()

    scraper = ScreenerScraper()
    total = len(tickers)
    success = skipped = failed = 0

    for i, ticker in enumerate(tickers, 1):
        cache_path = os.path.join(SHAREHOLDING_DIR, f"{ticker}.json")

        if not force and os.path.exists(cache_path):
            skipped += 1
            print(f"[{i}/{total}] {ticker}... skipped (cached)")
            continue

        print(f"[{i}/{total}] {ticker}... ", end="", flush=True)

        html, variant = scraper.fetch_company_html(ticker)
        if not html:
            failed += 1
            print("FAILED (no data)")
            logger.warning(f"Shareholding fetch failed for {ticker}")
            continue

        data = parse_company_page(html, ticker)
        sh = data.get("shareholding", {})

        if not sh.get("years") or not sh.get("data"):
            failed += 1
            print("FAILED (no shareholding)")
            continue

        record = {
            "ticker": ticker,
            "name": data.get("name"),
            "sector": data.get("sector"),
            "industry": data.get("industry"),
            "shareholding": sh,
            "fetched_at": datetime.now().isoformat(),
        }

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        success += 1
        print("OK")

    # Rebuild aggregate index
    _build_index()

    return {"success": success, "skipped": skipped, "failed": failed, "total": total}


# ── Index builder ────────────────────────────────────────────────────────────

def _build_index():
    """Aggregate per-ticker JSONs into data/shareholding/_index.json."""
    companies = []

    for fname in sorted(os.listdir(SHAREHOLDING_DIR)):
        if fname.startswith("_") or not fname.endswith(".json"):
            continue

        path = os.path.join(SHAREHOLDING_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            rec = json.load(f)

        sh = rec.get("shareholding", {})
        quarters = sh.get("years", [])
        data = sh.get("data", {})

        if len(quarters) < 2:
            continue

        # Find FII/DII rows — screener.in uses various labels
        fii_key = _find_key(data, ["FIIs", "FII", "Foreign Institutions",
                                    "Foreign Inst"])
        dii_key = _find_key(data, ["DIIs", "DII", "Domestic Institutions",
                                    "Domestic Inst"])
        prom_key = _find_key(data, ["Promoters", "Promoter"])
        pub_key = _find_key(data, ["Public", "Others"])

        companies.append({
            "ticker": rec["ticker"],
            "name": rec.get("name"),
            "sector": rec.get("sector"),
            "industry": rec.get("industry"),
            "quarters": quarters,
            "fii": data.get(fii_key, []) if fii_key else [],
            "dii": data.get(dii_key, []) if dii_key else [],
            "promoters": data.get(prom_key, []) if prom_key else [],
            "public": data.get(pub_key, []) if pub_key else [],
        })

    index = {
        "generated_at": datetime.now().isoformat(),
        "count": len(companies),
        "companies": companies,
    }

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

    logger.info(f"Shareholding index built: {len(companies)} companies")
    return index


def _find_key(data, candidates):
    """Find the first matching key from candidates in data dict."""
    for c in candidates:
        if c in data:
            return c
    return None


# ── HTML Dashboard Generator ─────────────────────────────────────────────────

def generate_shareholding_dashboard(output_dir=None):
    """Generate self-contained HTML dashboard from cached _index.json.

    Returns filepath of generated HTML.
    """
    if not os.path.exists(INDEX_FILE):
        # Try building index from cached files
        _build_index()
        if not os.path.exists(INDEX_FILE):
            raise FileNotFoundError(
                "No shareholding data found. Run 'shareholding-fetch' first."
            )

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index = json.load(f)

    companies = index.get("companies", [])
    if not companies:
        raise ValueError("Index has no companies.")

    # Build QoQ data (last 12 quarters) and YoY data (last 5 March entries)
    qoq_data = _prepare_qoq(companies, n_quarters=12)
    yoy_data = _prepare_yoy(companies, n_years=5)

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  "output", "dashboard")
    os.makedirs(output_dir, exist_ok=True)

    html = _render_html(qoq_data, yoy_data, index.get("generated_at", ""))
    filepath = os.path.join(output_dir, "shareholding_dashboard.html")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Shareholding dashboard: {filepath}")
    return filepath


def _prepare_qoq(companies, n_quarters=12):
    """Prepare QoQ view — last N quarters for each company."""
    result = []
    for c in companies:
        quarters = c["quarters"][-n_quarters:]
        fii = c["fii"][-n_quarters:]
        dii = c["dii"][-n_quarters:]
        promoters = c["promoters"][-n_quarters:]
        public = c["public"][-n_quarters:]

        # Pad to match quarters length
        fii = _pad(fii, len(quarters))
        dii = _pad(dii, len(quarters))
        promoters = _pad(promoters, len(quarters))
        public = _pad(public, len(quarters))

        fii_change = _compute_change(fii)
        dii_change = _compute_change(dii)

        result.append({
            "ticker": c["ticker"],
            "name": c.get("name", ""),
            "sector": c.get("sector", ""),
            "quarters": quarters,
            "fii": fii,
            "dii": dii,
            "promoters": promoters,
            "public": public,
            "fii_change": fii_change,
            "dii_change": dii_change,
        })

    return result


def _prepare_yoy(companies, n_years=5):
    """Prepare YoY view — last N March entries (fiscal year-end)."""
    result = []
    for c in companies:
        quarters = c["quarters"]
        fii_all = c["fii"]
        dii_all = c["dii"]
        prom_all = c["promoters"]
        pub_all = c["public"]

        # Find March entries (fiscal year-end)
        march_indices = [i for i, q in enumerate(quarters) if "Mar" in str(q)]

        # If no March entries, try any annual-looking entry
        if not march_indices:
            march_indices = list(range(len(quarters)))

        march_indices = march_indices[-n_years:]

        years = [quarters[i] for i in march_indices]
        fii = [fii_all[i] if i < len(fii_all) else None for i in march_indices]
        dii = [dii_all[i] if i < len(dii_all) else None for i in march_indices]
        promoters = [prom_all[i] if i < len(prom_all) else None for i in march_indices]
        public = [pub_all[i] if i < len(pub_all) else None for i in march_indices]

        fii_change = _compute_change(fii)
        dii_change = _compute_change(dii)

        result.append({
            "ticker": c["ticker"],
            "name": c.get("name", ""),
            "sector": c.get("sector", ""),
            "quarters": years,
            "fii": fii,
            "dii": dii,
            "promoters": promoters,
            "public": public,
            "fii_change": fii_change,
            "dii_change": dii_change,
        })

    return result


def _pad(values, length):
    """Pad list with None to reach target length (from the left)."""
    if len(values) >= length:
        return values[-length:]
    return [None] * (length - len(values)) + values


def _compute_change(values):
    """Compute change from first non-None to last non-None value."""
    non_null = [v for v in values if v is not None]
    if len(non_null) >= 2:
        return round(non_null[-1] - non_null[0], 2)
    return None


# ── HTML Renderer ─────────────────────────────────────────────────────────────

def _render_html(qoq_data, yoy_data, generated_at):
    """Render the full self-contained HTML dashboard."""
    qoq_json = json.dumps(qoq_data, default=str)
    yoy_json = json.dumps(yoy_data, default=str)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FII / DII Shareholding Dashboard</title>
<style>
:root {{
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --red: #f85149;
    --green-bg: rgba(63, 185, 80, 0.1);
    --red-bg: rgba(248, 81, 73, 0.1);
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
}}
.header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
}}
.header h1 {{ font-size: 20px; font-weight: 600; }}
.header .meta {{ color: var(--text-muted); font-size: 13px; }}

.controls {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
}}
.toggle-group {{
    display: flex;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
}}
.toggle-btn {{
    padding: 6px 16px;
    background: transparent;
    color: var(--text-muted);
    border: none;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: all 0.15s;
}}
.toggle-btn.active {{
    background: var(--accent);
    color: #fff;
}}
.search-box {{
    padding: 6px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 13px;
    width: 220px;
}}
.search-box::placeholder {{ color: var(--text-muted); }}
select.filter {{
    padding: 6px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 13px;
}}
.quick-filters {{
    display: flex;
    gap: 8px;
}}
.qf-btn {{
    padding: 4px 12px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 16px;
    color: var(--text-muted);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s;
}}
.qf-btn.active {{
    border-color: var(--accent);
    color: var(--accent);
    background: rgba(88, 166, 255, 0.1);
}}

.stats-bar {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 10px 24px;
    display: flex;
    gap: 32px;
    font-size: 13px;
    color: var(--text-muted);
}}
.stat-item span {{ color: var(--text); font-weight: 600; }}

.table-container {{
    overflow-x: auto;
    overflow-y: auto;
    max-height: calc(100vh - 180px);
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    white-space: nowrap;
}}
thead {{
    position: sticky;
    top: 0;
    z-index: 10;
}}
thead th {{
    background: var(--surface);
    border-bottom: 2px solid var(--border);
    padding: 8px 10px;
    text-align: right;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    color: var(--text-muted);
    cursor: pointer;
    user-select: none;
    position: relative;
}}
thead th:first-child,
thead th:nth-child(2),
thead th:nth-child(3) {{
    text-align: left;
    position: sticky;
    z-index: 11;
    background: var(--surface);
}}
thead th:first-child {{ left: 0; min-width: 80px; }}
thead th:nth-child(2) {{ left: 80px; min-width: 180px; }}
thead th:nth-child(3) {{ left: 260px; min-width: 120px; }}

thead th:hover {{ color: var(--accent); }}
thead th .sort-arrow {{ font-size: 10px; margin-left: 3px; }}

/* Section header rows in thead */
tr.section-header th {{
    text-align: center;
    font-size: 12px;
    color: var(--text);
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
}}
tr.section-header th.fii-section {{ color: #58a6ff; }}
tr.section-header th.dii-section {{ color: #d2a8ff; }}
tr.section-header th.info-section {{ color: var(--text-muted); }}

tbody td {{
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    text-align: right;
}}
tbody td:first-child,
tbody td:nth-child(2),
tbody td:nth-child(3) {{
    text-align: left;
    position: sticky;
    background: var(--bg);
    z-index: 5;
}}
tbody td:first-child {{ left: 0; min-width: 80px; font-weight: 600; color: var(--accent); }}
tbody td:nth-child(2) {{ left: 80px; min-width: 180px; }}
tbody td:nth-child(3) {{ left: 260px; min-width: 120px; color: var(--text-muted); }}

tbody tr:hover td {{ background: var(--surface); }}

.change-pos {{ color: var(--green); font-weight: 600; }}
.change-neg {{ color: var(--red); font-weight: 600; }}
.cell-up {{ background: var(--green-bg); }}
.cell-down {{ background: var(--red-bg); }}

.hidden {{ display: none; }}

/* Category selector */
.cat-group {{
    display: flex;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
}}
.cat-btn {{
    padding: 6px 14px;
    background: transparent;
    color: var(--text-muted);
    border: none;
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: all 0.15s;
}}
.cat-btn.active {{
    background: #8b5cf6;
    color: #fff;
}}
</style>
</head>
<body>

<div class="header">
    <h1>FII / DII Shareholding — Nifty 500</h1>
    <span class="meta">Data as of {generated_at[:10] if generated_at else 'N/A'} &bull; <span id="visibleCount"></span> companies</span>
</div>

<div class="controls">
    <div class="toggle-group">
        <button class="toggle-btn active" data-view="qoq">QoQ (12 Qtrs)</button>
        <button class="toggle-btn" data-view="yoy">YoY (Annual)</button>
    </div>
    <div class="cat-group">
        <button class="cat-btn active" data-cat="fii">FII</button>
        <button class="cat-btn" data-cat="dii">DII</button>
        <button class="cat-btn" data-cat="all">Both</button>
    </div>
    <input class="search-box" type="text" placeholder="Search ticker or company..." id="searchBox">
    <select class="filter" id="sectorFilter">
        <option value="">All Sectors</option>
    </select>
    <div class="quick-filters">
        <button class="qf-btn" data-qf="fii-up">FII Increase</button>
        <button class="qf-btn" data-qf="fii-down">FII Decrease</button>
        <button class="qf-btn" data-qf="dii-up">DII Increase</button>
        <button class="qf-btn" data-qf="dii-down">DII Decrease</button>
    </div>
</div>

<div class="stats-bar" id="statsBar"></div>

<div class="table-container">
    <table id="mainTable">
        <thead id="tableHead"></thead>
        <tbody id="tableBody"></tbody>
    </table>
</div>

<script>
const QOQ_DATA = {qoq_json};
const YOY_DATA = {yoy_json};

let currentView = 'qoq';
let currentCat = 'fii';
let currentSort = {{ col: null, asc: true }};
let activeQF = null;
let currentData = QOQ_DATA;

function getData() {{
    return currentView === 'qoq' ? QOQ_DATA : YOY_DATA;
}}

function getQuarters(data) {{
    // Find the company with the most quarters to use as header
    let maxQ = [];
    data.forEach(c => {{
        if (c.quarters.length > maxQ.length) maxQ = c.quarters;
    }});
    return maxQ;
}}

function fmt(v) {{
    if (v === null || v === undefined) return '-';
    return Number(v).toFixed(1);
}}

function changeClass(v) {{
    if (v === null || v === undefined) return '';
    return v > 0 ? 'change-pos' : v < 0 ? 'change-neg' : '';
}}

function changeText(v) {{
    if (v === null || v === undefined) return '-';
    const prefix = v > 0 ? '+' : '';
    return prefix + v.toFixed(2) + 'pp';
}}

function cellShade(val, prevVal) {{
    if (val === null || prevVal === null || val === undefined || prevVal === undefined) return '';
    if (val > prevVal) return 'cell-up';
    if (val < prevVal) return 'cell-down';
    return '';
}}

// ── Populate sector filter ───────────────────────────────────────
function populateSectors() {{
    const sectors = new Set();
    QOQ_DATA.forEach(c => {{ if (c.sector) sectors.add(c.sector); }});
    const sel = document.getElementById('sectorFilter');
    [...sectors].sort().forEach(s => {{
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        sel.appendChild(opt);
    }});
}}

// ── Render ────────────────────────────────────────────────────────
function render() {{
    const data = getData();
    const quarters = getQuarters(data);
    const thead = document.getElementById('tableHead');
    const tbody = document.getElementById('tableBody');

    const showFII = currentCat === 'fii' || currentCat === 'all';
    const showDII = currentCat === 'dii' || currentCat === 'all';

    // Build header
    let sectionRow = '<tr class="section-header"><th class="info-section" colspan="3"></th>';
    let headerRow = '<tr><th data-sort="ticker">Ticker</th><th data-sort="name">Company</th><th data-sort="sector">Sector</th>';

    if (showFII) {{
        const fiiCols = quarters.length + 1;
        sectionRow += `<th class="fii-section" colspan="${{fiiCols}}">FII / Foreign Institutional</th>`;
        quarters.forEach((q, i) => {{
            headerRow += `<th data-sort="fii_${{i}}">${{q}}</th>`;
        }});
        headerRow += '<th data-sort="fii_change" title="Change in percentage points from first to last period">Chg (pp)</th>';
    }}
    if (showDII) {{
        const diiCols = quarters.length + 1;
        sectionRow += `<th class="dii-section" colspan="${{diiCols}}">DII / Domestic Institutional</th>`;
        quarters.forEach((q, i) => {{
            headerRow += `<th data-sort="dii_${{i}}">${{q}}</th>`;
        }});
        headerRow += '<th data-sort="dii_change" title="Change in percentage points from first to last period">Chg (pp)</th>';
    }}

    sectionRow += '</tr>';
    headerRow += '</tr>';
    thead.innerHTML = sectionRow + headerRow;

    // Apply filters
    let filtered = applyFilters(data);

    // Sort
    if (currentSort.col) {{
        filtered = sortData(filtered, currentSort.col, currentSort.asc, quarters);
    }}

    // Build rows
    let html = '';
    filtered.forEach(c => {{
        // Align company data to the header quarters
        const alignedFII = alignToQuarters(c.quarters, c.fii, quarters);
        const alignedDII = alignToQuarters(c.quarters, c.dii, quarters);

        html += `<tr>`;
        html += `<td>${{c.ticker}}</td>`;
        html += `<td>${{c.name || ''}}</td>`;
        html += `<td>${{c.sector || ''}}</td>`;

        if (showFII) {{
            alignedFII.forEach((v, i) => {{
                const prev = i > 0 ? alignedFII[i - 1] : null;
                const shade = cellShade(v, prev);
                html += `<td class="${{shade}}">${{fmt(v)}}</td>`;
            }});
            html += `<td class="${{changeClass(c.fii_change)}}">${{changeText(c.fii_change)}}</td>`;
        }}
        if (showDII) {{
            alignedDII.forEach((v, i) => {{
                const prev = i > 0 ? alignedDII[i - 1] : null;
                const shade = cellShade(v, prev);
                html += `<td class="${{shade}}">${{fmt(v)}}</td>`;
            }});
            html += `<td class="${{changeClass(c.dii_change)}}">${{changeText(c.dii_change)}}</td>`;
        }}

        html += `</tr>`;
    }});

    tbody.innerHTML = html;
    document.getElementById('visibleCount').textContent = filtered.length;
    updateStats(filtered);
}}

function alignToQuarters(companyQ, companyVals, headerQ) {{
    // Map company's quarters to the header quarters
    const map = {{}};
    companyQ.forEach((q, i) => {{
        if (i < companyVals.length) map[q] = companyVals[i];
    }});
    return headerQ.map(q => map[q] !== undefined ? map[q] : null);
}}

// ── Filters ──────────────────────────────────────────────────────
function applyFilters(data) {{
    const search = document.getElementById('searchBox').value.toLowerCase();
    const sector = document.getElementById('sectorFilter').value;

    return data.filter(c => {{
        if (search && !(c.ticker || '').toLowerCase().includes(search) &&
            !(c.name || '').toLowerCase().includes(search)) return false;
        if (sector && c.sector !== sector) return false;
        if (activeQF === 'fii-up' && !(c.fii_change > 0)) return false;
        if (activeQF === 'fii-down' && !(c.fii_change < 0)) return false;
        if (activeQF === 'dii-up' && !(c.dii_change > 0)) return false;
        if (activeQF === 'dii-down' && !(c.dii_change < 0)) return false;
        return true;
    }});
}}

// ── Sort ──────────────────────────────────────────────────────────
function sortData(data, col, asc, quarters) {{
    const sorted = [...data];
    sorted.sort((a, b) => {{
        let va, vb;

        if (col === 'ticker') {{ va = a.ticker; vb = b.ticker; }}
        else if (col === 'name') {{ va = a.name || ''; vb = b.name || ''; }}
        else if (col === 'sector') {{ va = a.sector || ''; vb = b.sector || ''; }}
        else if (col === 'fii_change') {{ va = a.fii_change; vb = b.fii_change; }}
        else if (col === 'dii_change') {{ va = a.dii_change; vb = b.dii_change; }}
        else if (col.startsWith('fii_')) {{
            const idx = parseInt(col.split('_')[1]);
            const aq = alignToQuarters(a.quarters, a.fii, quarters);
            const bq = alignToQuarters(b.quarters, b.fii, quarters);
            va = aq[idx]; vb = bq[idx];
        }}
        else if (col.startsWith('dii_')) {{
            const idx = parseInt(col.split('_')[1]);
            const aq = alignToQuarters(a.quarters, a.dii, quarters);
            const bq = alignToQuarters(b.quarters, b.dii, quarters);
            va = aq[idx]; vb = bq[idx];
        }}

        if (va === null || va === undefined) va = -Infinity;
        if (vb === null || vb === undefined) vb = -Infinity;
        if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        return asc ? va - vb : vb - va;
    }});
    return sorted;
}}

// ── Stats ─────────────────────────────────────────────────────────
function updateStats(filtered) {{
    const total = filtered.length;
    const fiiUp = filtered.filter(c => c.fii_change > 0).length;
    const fiiDown = filtered.filter(c => c.fii_change < 0).length;
    const diiUp = filtered.filter(c => c.dii_change > 0).length;
    const diiDown = filtered.filter(c => c.dii_change < 0).length;

    // Average latest FII/DII
    const fiiVals = filtered.map(c => c.fii.filter(v => v !== null).pop()).filter(v => v !== undefined);
    const diiVals = filtered.map(c => c.dii.filter(v => v !== null).pop()).filter(v => v !== undefined);
    const avgFII = fiiVals.length ? (fiiVals.reduce((a, b) => a + b, 0) / fiiVals.length).toFixed(1) : '-';
    const avgDII = diiVals.length ? (diiVals.reduce((a, b) => a + b, 0) / diiVals.length).toFixed(1) : '-';

    document.getElementById('statsBar').innerHTML = `
        <div class="stat-item">Companies: <span>${{total}}</span></div>
        <div class="stat-item">Avg FII: <span>${{avgFII}}%</span></div>
        <div class="stat-item">Avg DII: <span>${{avgDII}}%</span></div>
        <div class="stat-item">FII &#9650;: <span style="color:var(--green)">${{fiiUp}}</span></div>
        <div class="stat-item">FII &#9660;: <span style="color:var(--red)">${{fiiDown}}</span></div>
        <div class="stat-item">DII &#9650;: <span style="color:var(--green)">${{diiUp}}</span></div>
        <div class="stat-item">DII &#9660;: <span style="color:var(--red)">${{diiDown}}</span></div>
    `;
}}

// ── Event Listeners ──────────────────────────────────────────────
document.querySelectorAll('.toggle-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentView = btn.dataset.view;
        currentSort = {{ col: null, asc: true }};
        render();
    }});
}});

document.querySelectorAll('.cat-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentCat = btn.dataset.cat;
        currentSort = {{ col: null, asc: true }};
        render();
    }});
}});

document.getElementById('searchBox').addEventListener('input', render);
document.getElementById('sectorFilter').addEventListener('change', render);

document.querySelectorAll('.qf-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
        if (activeQF === btn.dataset.qf) {{
            activeQF = null;
            btn.classList.remove('active');
        }} else {{
            document.querySelectorAll('.qf-btn').forEach(b => b.classList.remove('active'));
            activeQF = btn.dataset.qf;
            btn.classList.add('active');
        }}
        render();
    }});
}});

document.getElementById('tableHead').addEventListener('click', (e) => {{
    const th = e.target.closest('th');
    if (!th || !th.dataset.sort) return;
    const col = th.dataset.sort;
    if (currentSort.col === col) {{
        currentSort.asc = !currentSort.asc;
    }} else {{
        currentSort.col = col;
        currentSort.asc = col === 'ticker' || col === 'name' || col === 'sector';
    }}
    render();
}});

// ── Init ─────────────────────────────────────────────────────────
populateSectors();
render();
</script>
</body>
</html>"""
