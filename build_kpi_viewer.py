"""Build self-contained KPI viewer HTML with all JSON data embedded."""
import json
import os
import glob

DATA_DIR = os.path.join("data", "kpi_database")
OUTPUT = os.path.join("output", "kpi_viewer.html")

# Load all JSON files
all_data = {}
for f in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
    ticker = os.path.basename(f).replace(".json", "")
    with open(f, "r", encoding="utf-8") as fh:
        all_data[ticker] = json.load(fh)

print(f"Loaded {len(all_data)} tickers: {', '.join(sorted(all_data.keys()))}")

# Serialize to JSON, escaping </script> to prevent HTML parser breaking
json_str = json.dumps(all_data, ensure_ascii=True, separators=(",", ":"))
json_str = json_str.replace("</script>", "<\\/script>")
json_str = json_str.replace("</Script>", "<\\/Script>")

HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KPI Database Viewer</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #232733;
    --border: #2e3340;
    --text: #e4e6eb;
    --text-dim: #8b8f9a;
    --accent: #4f8cff;
    --green: #34d399;
    --red: #f87171;
    --amber: #fbbf24;
    --blue: #60a5fa;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); }

  /* Layout */
  .app { display: flex; height: 100vh; }
  .sidebar { width: 280px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
  .main { flex: 1; overflow-y: auto; padding: 32px 40px; }

  /* Sidebar */
  .sidebar-header { padding: 20px; border-bottom: 1px solid var(--border); }
  .sidebar-header h1 { font-size: 16px; font-weight: 600; color: var(--accent); letter-spacing: 0.5px; }
  .sidebar-header p { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
  .sidebar-search { padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .sidebar-search input {
    width: 100%; padding: 8px 12px; background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); font-size: 13px; outline: none;
  }
  .sidebar-search input:focus { border-color: var(--accent); }
  .company-list { flex: 1; overflow-y: auto; padding: 8px; min-height: 0; }
  .company-item {
    padding: 10px 12px; border-radius: 6px; cursor: pointer; margin-bottom: 2px;
    display: flex; justify-content: space-between; align-items: center; transition: background 0.15s;
  }
  .company-item:hover { background: var(--surface2); }
  .company-item.active { background: var(--accent); color: #fff; }
  .company-item .ticker { font-size: 13px; font-weight: 600; }
  .company-item .kpi-count { font-size: 11px; color: var(--text-dim); background: var(--bg); padding: 2px 8px; border-radius: 10px; }
  .company-item.active .kpi-count { background: rgba(255,255,255,0.2); color: #fff; }

  /* Main Header */
  .company-header { margin-bottom: 28px; }
  .company-header h2 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
  .company-header .meta-row { display: flex; gap: 20px; font-size: 13px; color: var(--text-dim); flex-wrap: wrap; }
  .meta-tag { background: var(--surface); padding: 4px 10px; border-radius: 4px; border: 1px solid var(--border); }

  /* Category Sections */
  .category-section { margin-bottom: 32px; }
  .category-title {
    font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--accent); margin-bottom: 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
  }

  /* KPI Cards */
  .kpi-grid { display: grid; grid-template-columns: 1fr; gap: 8px; }
  .kpi-card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px 20px; transition: border-color 0.15s;
  }
  .kpi-card:hover { border-color: var(--accent); }
  .kpi-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
  .kpi-label { font-size: 14px; font-weight: 600; }
  .kpi-badges { display: flex; gap: 6px; flex-shrink: 0; }
  .badge {
    font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  .badge-trend { background: var(--surface2); color: var(--text-dim); }
  .badge-trend.improving, .badge-trend.increasing, .badge-trend.accelerating_growth,
  .badge-trend.strong_growth, .badge-trend.expanding_strongly, .badge-trend.rapidly_increasing { background: rgba(52,211,153,0.15); color: var(--green); }
  .badge-trend.declining, .badge-trend.decelerating, .badge-trend.contracting,
  .badge-trend.collapsing, .badge-trend.deteriorating { background: rgba(248,113,113,0.15); color: var(--red); }
  .badge-trend.stable, .badge-trend.flat, .badge-trend.mixed { background: rgba(251,191,36,0.15); color: var(--amber); }
  .badge-unit { background: var(--surface2); color: var(--text-dim); }
  .badge-consistency { background: rgba(79,140,255,0.1); color: var(--blue); }

  /* Values Table */
  .values-table { width: 100%; border-collapse: collapse; }
  .values-table th {
    font-size: 11px; font-weight: 600; color: var(--text-dim); text-transform: uppercase;
    letter-spacing: 0.5px; text-align: left; padding: 4px 12px 8px 0;
  }
  .values-table td { font-size: 13px; padding: 4px 12px 4px 0; }
  .values-table td.value { font-weight: 600; font-variant-numeric: tabular-nums; }
  .values-table td.yoy { font-size: 12px; }
  .values-table td.yoy.positive { color: var(--green); }
  .values-table td.yoy.negative { color: var(--red); }
  .tone-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
  .tone-dot.positive { background: var(--green); }
  .tone-dot.cautious { background: var(--amber); }
  .tone-dot.negative { background: var(--red); }
  .tone-dot.neutral, .tone-dot.not_reported { background: var(--text-dim); }
  .tone-label { font-size: 12px; color: var(--text-dim); }

  /* KPI Meta */
  .kpi-meta { display: flex; gap: 16px; margin-top: 8px; font-size: 11px; color: var(--text-dim); flex-wrap: wrap; }
  .kpi-meta span { display: flex; align-items: center; gap: 4px; }

  /* Missing KPIs */
  .missing-section { margin-top: 32px; }
  .missing-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: var(--red); margin-bottom: 8px; }
  .missing-item { font-size: 13px; color: var(--text-dim); padding: 6px 0; border-bottom: 1px solid var(--border); }
  .missing-item:last-child { border-bottom: none; }

  /* Extraction Notes */
  .notes-box {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px 20px; margin-top: 16px; font-size: 13px; color: var(--text-dim); line-height: 1.6;
  }
  .notes-box-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); margin-bottom: 8px; }

  /* Empty state */
  .empty-state { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--text-dim); font-size: 15px; }

  /* Filter pills */
  .filter-row { display: flex; gap: 6px; padding: 8px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; max-height: 120px; overflow-y: auto; flex-shrink: 0; }
  .filter-pill {
    font-size: 11px; padding: 4px 10px; border-radius: 12px; cursor: pointer;
    background: var(--bg); border: 1px solid var(--border); color: var(--text-dim); transition: all 0.15s;
  }
  .filter-pill:hover { border-color: var(--accent); color: var(--text); }
  .filter-pill.active { background: var(--accent); border-color: var(--accent); color: #fff; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

  /* Null values */
  .null-value { color: var(--text-dim); font-style: italic; }
</style>
</head>
<body>
<div class="app">
  <div class="sidebar">
    <div class="sidebar-header">
      <h1>KPI Database</h1>
      <p id="companyCount"></p>
    </div>
    <div class="sidebar-search">
      <input type="text" id="searchInput" placeholder="Search ticker or company..." />
    </div>
    <div class="filter-row" id="industryFilters"></div>
    <div class="company-list" id="companyList"></div>
  </div>
  <div class="main" id="mainContent">
    <div class="empty-state">Select a company from the sidebar to view KPIs</div>
  </div>
</div>

<script>
window.onerror = function(msg, url, line, col, err) {
  document.body.innerHTML = '<div style="color:red;padding:40px;font-size:16px;"><h2>JS Error</h2><pre>' + msg + '\nLine: ' + line + '\nCol: ' + col + '\n' + (err ? err.stack : '') + '</pre></div>';
};

const ALL_DATA = __DATA_PLACEHOLDER__;

var allData = ALL_DATA;
var TICKERS = Object.keys(allData).sort();
var currentTicker = null;
var activeIndustry = null;

function init() {
  document.getElementById('companyCount').textContent = TICKERS.length + ' companies loaded';
  buildIndustryFilters();
  renderCompanyList();
}

function buildIndustryFilters() {
  var industries = new Set();
  for (var ti = 0; ti < TICKERS.length; ti++) {
    var t = TICKERS[ti];
    if (allData[t].industry) industries.add(allData[t].industry);
  }
  var container = document.getElementById('industryFilters');
  const allPill = document.createElement('span');
  allPill.className = 'filter-pill active';
  allPill.textContent = 'All';
  allPill.onclick = function() { activeIndustry = null; updateFilters(); };
  container.appendChild(allPill);

  var sortedIndustries = Array.from(industries).sort();
  for (var i = 0; i < sortedIndustries.length; i++) {
    var ind = sortedIndustries[i];
    var pill = document.createElement('span');
    pill.className = 'filter-pill';
    pill.textContent = ind.replace(/_/g, ' ');
    pill.dataset.industry = ind;
    pill.onclick = (function(industry) {
      return function() { activeIndustry = industry; updateFilters(); };
    })(ind);
    container.appendChild(pill);
  }
}

function updateFilters() {
  document.querySelectorAll('.filter-pill').forEach(function(p) {
    if (activeIndustry === null) p.classList.toggle('active', !p.dataset.industry);
    else p.classList.toggle('active', p.dataset.industry === activeIndustry);
  });
  renderCompanyList();
}

function renderCompanyList() {
  var search = document.getElementById('searchInput').value.toLowerCase();
  var container = document.getElementById('companyList');
  container.innerHTML = '';

  for (var idx = 0; idx < TICKERS.length; idx++) {
    var ticker = TICKERS[idx];
    var d = allData[ticker];
    var matchSearch = !search || ticker.toLowerCase().includes(search) || (d.company || '').toLowerCase().includes(search);
    var matchIndustry = !activeIndustry || d.industry === activeIndustry;
    if (!matchSearch || !matchIndustry) continue;

    var item = document.createElement('div');
    item.className = 'company-item' + (ticker === currentTicker ? ' active' : '');
    var kpiCount = (d.meta && d.meta.total_kpis) ? d.meta.total_kpis : Object.keys(d.kpis).length;
    item.innerHTML = '<span class="ticker">' + ticker + '</span><span class="kpi-count">' + kpiCount + ' KPIs</span>';
    item.onclick = (function(t) { return function() { selectCompany(t); }; })(ticker);
    container.appendChild(item);
  }
}

document.getElementById('searchInput').addEventListener('input', renderCompanyList);

function selectCompany(ticker) {
  currentTicker = ticker;
  renderCompanyList();
  renderMain(ticker);
}

function formatValue(val, unit) {
  if (val === null || val === undefined) return '<span class="null-value">\u2014</span>';
  if (typeof val === 'number') {
    if (unit === '%' || unit === 'x') return val.toLocaleString(undefined, { maximumFractionDigits: 2 });
    if (val >= 10000) return val.toLocaleString();
    return val.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(val);
}

function yoyClass(yoy) {
  if (!yoy) return '';
  if (yoy.charAt(0) === '+') return 'positive';
  if (yoy.charAt(0) === '-') return 'negative';
  return '';
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderMain(ticker) {
  var d = allData[ticker];
  var main = document.getElementById('mainContent');

  // Group KPIs by category
  var categories = {};
  var kpiKeys = Object.keys(d.kpis);
  for (var i = 0; i < kpiKeys.length; i++) {
    var key = kpiKeys[i];
    var kpi = d.kpis[key];
    var cat = kpi.category || 'other';
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push(Object.assign({ key: key }, kpi));
  }

  // Get all years across all KPIs
  var allYears = {};
  for (var k in d.kpis) {
    if (d.kpis[k].values) {
      for (var yr in d.kpis[k].values) allYears[yr] = true;
    }
  }
  var years = Object.keys(allYears).sort();

  var html = '<div class="company-header">' +
    '<h2>' + escapeHtml(d.company || ticker) + '</h2>' +
    '<div class="meta-row">' +
    '<span class="meta-tag">' + escapeHtml(ticker) + '</span>' +
    '<span class="meta-tag">' + escapeHtml((d.industry || '').replace(/_/g, ' ')) + '</span>' +
    '<span class="meta-tag">Years: ' + escapeHtml((d.years_covered || []).join(', ')) + '</span>' +
    '<span class="meta-tag">Updated: ' + escapeHtml(d.last_updated || '\u2014') + '</span>' +
    '<span class="meta-tag">' + ((d.meta && d.meta.total_kpis) || Object.keys(d.kpis).length) + ' KPIs (' + ((d.meta && d.meta.core_kpis) || '?') + ' core)</span>' +
    '</div></div>';

  var catOrder = ['order_book','revenue_quality','market_position','operational_efficiency','capacity','growth_driver','innovation','sustainability','other'];
  var sortedCats = Object.keys(categories).sort(function(a, b) {
    var ai = catOrder.indexOf(a), bi = catOrder.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  for (var ci = 0; ci < sortedCats.length; ci++) {
    var cat = sortedCats[ci];
    var kpis = categories[cat];
    html += '<div class="category-section">' +
      '<div class="category-title">' + escapeHtml(cat.replace(/_/g, ' ')) + ' (' + kpis.length + ')</div>' +
      '<div class="kpi-grid">';

    for (var ki = 0; ki < kpis.length; ki++) {
      var kpi = kpis[ki];
      var trendClass = (kpi.trend || '').replace(/\s+/g, '_').toLowerCase();
      html += '<div class="kpi-card">' +
        '<div class="kpi-card-header">' +
        '<span class="kpi-label">' + escapeHtml(kpi.label) + '</span>' +
        '<div class="kpi-badges">' +
        '<span class="badge badge-unit">' + escapeHtml(kpi.unit || '') + '</span>' +
        '<span class="badge badge-trend ' + trendClass + '">' + escapeHtml((kpi.trend || 'n/a').replace(/_/g, ' ')) + '</span>' +
        '<span class="badge badge-consistency">' + escapeHtml(kpi.consistency || '') + '</span>' +
        '</div></div>' +
        '<table class="values-table"><thead><tr>' +
        '<th>Year</th><th>Value</th><th>YoY</th><th>Mgmt Tone</th>' +
        '</tr></thead><tbody>';

      for (var yi = 0; yi < years.length; yi++) {
        var yr = years[yi];
        var v = (kpi.values || {})[yr];
        if (!v) continue;
        var toneColor = v.mgmt_tone || 'neutral';
        html += '<tr>' +
          '<td>' + escapeHtml(yr) + '</td>' +
          '<td class="value">' + formatValue(v.value, kpi.unit) + '</td>' +
          '<td class="yoy ' + yoyClass(v.yoy_change) + '">' + escapeHtml(v.yoy_change || '\u2014') + '</td>' +
          '<td><span class="tone-dot ' + toneColor + '"></span><span class="tone-label">' + escapeHtml(v.mgmt_tone || '\u2014') + '</span></td>' +
          '</tr>';
      }

      html += '</tbody></table>';

      // Meta row
      var metaParts = [];
      if (kpi.cagr) metaParts.push('CAGR: ' + escapeHtml(kpi.cagr));
      if (kpi.direction_preference) metaParts.push('Pref: ' + escapeHtml(kpi.direction_preference.replace(/_/g, ' ')));
      if (kpi.source_blocks) metaParts.push('Source: ' + escapeHtml(kpi.source_blocks.join(', ')));
      if (kpi.note) metaParts.push(escapeHtml(kpi.note));

      if (metaParts.length) {
        html += '<div class="kpi-meta">';
        for (var mi = 0; mi < metaParts.length; mi++) {
          html += '<span>' + metaParts[mi] + '</span>';
        }
        html += '</div>';
      }

      html += '</div>'; // kpi-card
    }

    html += '</div></div>'; // kpi-grid, category-section
  }

  // Missing KPIs
  if (d.meta && d.meta.missing_expected_kpis && d.meta.missing_expected_kpis.length) {
    html += '<div class="missing-section">' +
      '<div class="missing-title">Missing / Undisclosed KPIs (' + d.meta.missing_expected_kpis.length + ')</div>';
    for (var mi2 = 0; mi2 < d.meta.missing_expected_kpis.length; mi2++) {
      html += '<div class="missing-item">' + escapeHtml(d.meta.missing_expected_kpis[mi2]) + '</div>';
    }
    html += '</div>';
  }

  // Extraction Notes
  if (d.meta && d.meta.extraction_notes) {
    html += '<div class="notes-box">' +
      '<div class="notes-box-title">Extraction Notes</div>' +
      escapeHtml(d.meta.extraction_notes) +
      '</div>';
  }

  main.innerHTML = html;
  main.scrollTop = 0;
}

document.addEventListener('DOMContentLoaded', function() {
  try { init(); } catch(e) {
    document.body.innerHTML = '<div style="color:red;padding:40px;font-size:16px;"><h2>Init Error</h2><pre>' + e.message + '\n' + e.stack + '</pre></div>';
  }
});
</script>
</body>
</html>'''

# Replace placeholder with actual data
html_output = HTML.replace('__DATA_PLACEHOLDER__', json_str)

os.makedirs("output", exist_ok=True)
with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(html_output)

size_kb = os.path.getsize(OUTPUT) / 1024
print(f"Written {OUTPUT} ({size_kb:.0f} KB) with {len(all_data)} companies")
