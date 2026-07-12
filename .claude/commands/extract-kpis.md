# Operational KPI Extractor

You are extracting management-highlighted operational KPIs from Indian company MD&A files and building a structured longitudinal database. The goal: capture the metrics management considers important enough to report every year — these reveal what drives the business.

**Input:** User provides a ticker (e.g., `JLHL`) and optionally a specific FY year. If no year specified, process ALL available MDA files for that ticker.

**Project root:** `C:/Users/VinothRajapandian/Personal Claude/Stock Monitor`

---

## Core Principle: Organic Discovery, Not Pre-Determination

Do NOT start with a pre-defined list of KPIs. Read what management actually reports. Every company and industry surfaces different metrics. The skill discovers KPIs from the text, not from a template.

**What qualifies as an operational KPI:**
- Metrics management uses to describe business performance BEYOND standard financials
- Numbers that reveal operational health, competitive position, or growth drivers
- Industry-specific measures (ARPOB, order book, ANDA pipeline, AUM, etc.)
- Segment splits, geographic splits, customer/product mix ratios
- Capacity, utilization, efficiency, and throughput metrics
- Pipeline, backlog, and forward-looking operational indicators

**What to EXCLUDE — these belong in other analyses, not the KPI database:**
- **Standard financials** (already in ticker Excel): Revenue, EBITDA, PAT, EPS, margins, ROE, ROCE, D/E, current ratio, total assets, equity, borrowings, CFO, FCF, trade receivables, inventory, payables
- **Financial ratios**: Debtors turnover days, accounts payable days, inventory days, cash conversion cycle, DSCR, interest coverage — these are tracked in `/past-performance` and `/red-flag`
- **Balance sheet items**: CWIP, capex amounts, PPE, cash & equivalents, net debt — these are in the Excel
- **Governance metrics**: KMP/director remuneration, CSR donations, related party transaction values, auditor details — these belong in `/integrity` and `/red-flag`
- **Shareholding data**: Promoter/FII/DII holdings — already in Excel
- **Dividend per share**: Already in Excel valuation sheet

**The test: Is this metric OPERATIONAL (how the business runs) or FINANCIAL (how the numbers look)?** Only extract operational metrics. If an analyst can get it from the ticker Excel or from `/red-flag` output, skip it.

**INCLUDE — operational metrics not available elsewhere:**
- Segment-wise revenue breakdown (Excel has total, not segments)
- Geographic revenue split
- Customer/product mix ratios and concentration
- R&D spend as % of revenue
- Employee count, doctor/specialist count, productivity metrics
- Capacity, utilization, throughput, volume metrics (beds, patients, orders, transactions)
- Pipeline, backlog, order book, forward-looking operational indicators
- Industry-specific operational measures (ARPOB, ALOS, ANDA pipeline, AUM, etc.)
- Cost structure ratios (materials/employee/other as % of revenue) if management tracks them

---

## Orchestration Flow

### Step 1: Locate MDA Files

Find all available MDA context files:
```
data/annual_reports/{TICKER}/{TICKER}_MDA_*context.md
```

Sort by fiscal year. If user specified a year, process only that year. Otherwise process ALL years chronologically — this is critical for longitudinal tracking.

### Step 2: Load Existing KPI Database (if any)

Check for: `data/kpi_database/{TICKER}.json`

If it exists, load it. This tells you:
- Which KPIs were previously discovered
- Which years are already extracted
- The established KPI keys for this company

Skip years already in the database unless user explicitly asks to re-extract.

### Step 3: Extract KPIs from Each MDA File

For each MDA file (chronological order), read Block 2 (Financial Performance) and Block 3 (Operational Highlights) primarily. Also scan Block 1 (Business Overview), Block 1A (Strategic Priorities), Block 6 (Capital Allocation), and Block 7 (Management Outlook) for operational metrics.

**Extraction rules:**

1. **Capture every named quantitative metric** that isn't in the exclusion list above
2. **Preserve the exact label management uses** — if they say "ARPOB" don't rename it to "average_revenue_per_bed"
3. **Capture the unit** — Rs Mn, %, days, MW, beds, folios, etc.
4. **Capture the value** — numeric, cleaned (remove commas, convert lakhs/crores consistently)
5. **Capture the context** — which block/section it appeared in
6. **Flag direction** — does management present this as positive or negative? (e.g., "grew 25%" vs "declined to")

**For the FIRST year being extracted (no prior database):**
- Discover freely — every operational metric management reports is a candidate
- Assign a stable `key` to each metric (snake_case, descriptive: `order_booking`, `arpob`, `para_iv_pipeline`)
- These keys become the longitudinal tracking identifiers

**For SUBSEQUENT years:**
- First, check every previously-discovered KPI key — is it present this year? Record value or mark as `"not_reported"`
- Then, scan for NEW metrics not in the existing key set — add them with a new key
- A metric that disappears is informative — track it as `"not_reported"` not by deleting the key

### Step 3A: Supplementary PDF Extraction (if needed)

The MDA context files may not capture all operational KPIs — some are buried in operational review pages, statistical tables, or investor presentation sections of the annual report that the `/extract-sections` skill skips.

**After extracting from MDA files, check for gaps in expected operational metrics:**
- Hospitals: doctor/specialist count, IP volume (admissions/discharges), OP volume (footfall/visits), surgeries performed, ICU bed count, OT count
- Manufacturing: order book, capacity utilization, production volume, dispatch volume, plant count
- Pharma: ANDA/DMF pipeline, molecule count, plant capacity, API production volume
- Financial services: transaction volume, active accounts, AUM, market share, digital adoption
- IT services: headcount, utilization rate, attrition, active clients, large deal count

**If critical operational metrics are missing from the MDA extraction**, read the annual report PDF directly:
```
data/annual_reports/{TICKER}/{TICKER}_AnnualReport_FY{YEAR}.pdf
```
Scan the operational review, statistical summary, or performance highlights pages (typically pages 5-30) for the missing metrics. Extract and add them to the database with `source_blocks: ["PDF direct"]`.

**Do NOT re-read the PDF if the MDA extraction already covers the key operational metrics.** This step is a safety net for gaps, not a routine step.

### Step 3B: Stated vs Achieved — Integrity Enrichment

This is the critical bridge between the KPI database and the integrity pipeline. For each KPI, track what management **said** about it (from the prior year's outlook) alongside what **actually happened**.

**How it works:**

For each year FY{N} being extracted:
1. Read Block 7 (Management Outlook & Guidance) from the **prior year** FY{N-1}
2. For each discovered KPI, check: did management make any forward-looking statement about this metric or its underlying driver in FY{N-1}?
3. If yes, record the statement and assess the verdict

**Matching rules:**
- Statements don't need to name the exact KPI — "robust export order pipeline" maps to `order_booking_export`
- "Expanding into 3 new geographies" maps to `countries_presence`
- "ARPOB improvement driven by case mix" maps to `arpob`
- "Double the sales force" maps to `salesforce_size`
- Match directional claims too: "aftermarket will grow faster than product" → compare `revenue_aftermarket` growth vs `revenue_product` growth

**Verdict logic:**
- `EXCEEDED` — actual outcome significantly exceeded what was stated (>120% of target if quantified, or clearly surpassed directional claim)
- `DELIVERED` — outcome matches the commitment (met quantified target, or directional claim confirmed)
- `PARTIALLY` — directionally correct but fell short of target, or only some aspects of the claim materialized
- `MISSED` — commitment clearly not met; actual moved in opposite direction or didn't materialize
- `ABANDONED` — commitment from prior year silently dropped, no mention in current year
- `NOT_TRACKABLE` — statement too vague to verify against any KPI ("we remain optimistic")

**For the FIRST year (no prior year to compare):**
- Skip this step — there's no FY{N-1} outlook to check against
- But DO capture any forward-looking statements in Block 7 of this year — they become the "stated" for next year's comparison

**Record in the JSON value entry:**

```json
"FY2024": {
  "value": 18783,
  "yoy_change": "+17%",
  "mgmt_tone": "positive",
  "stated": {
    "source_fy": "FY2023",
    "management_said": "Robust export and aftermarket order bookings with thriving enquiry pipeline",
    "quantified": false,
    "verdict": "DELIVERED"
  }
}
```

If no relevant prior-year statement exists for a KPI, omit the `stated` field entirely (don't add `"stated": null`).

**Also capture forward-looking statements for NEXT year:**
For each KPI, if Block 7 of the CURRENT year contains a forward-looking claim relevant to it, store it in a top-level `forward_guidance` object:

```json
"forward_guidance": {
  "FY2025": {
    "order_booking": "Highest-ever order booking provides strong revenue visibility for FY26",
    "export_share": "API segment expected to outpace other segments in growth",
    "r_and_d_expenditure": "Investing in R&D for energy transition solutions"
  }
}
```

This way, when the NEXT extraction runs for FY2026, it can read `forward_guidance.FY2025` to auto-populate the `stated` field.

### Step 4: Classify KPIs

After extraction, classify each KPI into one of these categories:

| Category | Description | Examples |
|---|---|---|
| `growth_driver` | Metrics that indicate top-line growth potential | Order book, pipeline, new store count, AUM |
| `operational_efficiency` | Metrics showing how well the business operates | Utilization, ARPOB, yield, throughput |
| `market_position` | Competitive standing indicators | Market share, ranking, customer count |
| `revenue_quality` | Mix and concentration metrics | Segment split, geo split, customer concentration |
| `capacity` | Current and planned capacity | Beds, MW, plants, employees |
| `innovation` | R&D and pipeline metrics | Patents, ANDAs, new products |
| `sustainability` | ESG and long-term viability | Attrition, safety, environmental |

### Step 4B: Assign Impact Tier

For each KPI, assign an `impact_tier` that classifies how directly it affects the company's revenue and profit:

| Tier | Definition | Assignment Rule | Examples |
|---|---|---|---|
| `critical` | Directly drives revenue, profit, or margin. A material move in this KPI will show up in the P&L within 1-2 quarters. | Segment revenues, segment margins, pricing, order book (converts to revenue), capacity utilization (constrains revenue), ARPOB/ARPU (revenue per unit), volume metrics that directly multiply into revenue | Cigarettes segment result, FMCG-Others EBITDA margin, order booking, ARPOB, capacity utilization %, ASP |
| `supporting` | Influences P&L indirectly or is a leading indicator. Important for thesis but doesn't move the P&L by itself. | Market share (competitive position → future pricing power), distribution reach (enables but doesn't guarantee revenue), customer count (leading indicator), backlog (forward visibility), mix ratios (quality of revenue) | Household reach, market share, new gen channel %, stockist network, export share, customer concentration |
| `context` | Industry backdrop, ESG, operational hygiene. Useful for understanding but not P&L-moving. | Industry size, sustainability stats, employee count, R&D intensity, CSR spend, certifications, awards | Industry market size, renewable energy %, water positive years, employee count, patent applications |

**Assignment rules:**
1. **Start from the P&L and work backwards.** If a KPI directly multiplies into a revenue or cost line item, it's `critical`.
2. **Leading indicators are `supporting`**, not `critical` — they signal future revenue but don't guarantee it.
3. **When in doubt between `critical` and `supporting`**: ask "If this KPI moved 20%, would an analyst revise their earnings estimate?" If yes → `critical`. If "maybe, depends on other factors" → `supporting`.
4. **Segment-level revenue and margin KPIs are always `critical`** — they are the P&L itself, just disaggregated.
5. **Industry/market size is always `context`** — it describes the opportunity, not the company's capture of it.

### Step 5: Build Longitudinal View

For each KPI, compute across available years:
- **Trend**: increasing / decreasing / stable / volatile
- **CAGR** (if 3+ years of data)
- **Consistency**: reported in X of Y years (e.g., "5/6 years" — a metric reported every year is management's core KPI)
- **Latest direction**: YoY change in most recent year

### Step 6: Write Output

#### 6A: Per-Company JSON Database

Save to: `data/kpi_database/{TICKER}.json`

```json
{
  "ticker": "{TICKER}",
  "company": "{Full company name}",
  "industry": "{industry_slug}",
  "last_updated": "{ISO date}",
  "years_covered": ["FY2020", "FY2021", ...],
  "kpis": {
    "{kpi_key}": {
      "label": "{Management's label}",
      "unit": "{unit}",
      "category": "{category from Step 4}",
      "impact_tier": "critical | supporting | context",
      "direction_preference": "higher_better | lower_better | context_dependent",
      "consistency": "{X}/{Y} years reported",
      "values": {
        "FY2020": {"value": 123.4, "yoy_change": null, "mgmt_tone": "positive"},
        "FY2021": {
          "value": 145.6, "yoy_change": "+18.0%", "mgmt_tone": "positive",
          "stated": {
            "source_fy": "FY2020",
            "management_said": "Expect strong growth in order intake driven by domestic enquiry pipeline",
            "quantified": false,
            "verdict": "DELIVERED"
          }
        },
        "FY2022": "not_reported",
        "FY2023": {"value": 180.2, "yoy_change": null, "mgmt_tone": "neutral"}
      },
      "trend": "increasing",
      "cagr": "13.5%",
      "source_blocks": ["Block 2", "Block 3"]
    }
  },
  "forward_guidance": {
    "FY2023": {
      "order_booking": "Strong carry-forward order book of Rs 13,280 Mn; thriving enquiry pipeline",
      "export_share": "Expanding market share internationally"
    }
  },
  "meta": {
    "total_kpis": 25,
    "core_kpis": 18,
    "integrity_coverage": "4/5 years have prior-year guidance comparison",
    "delivery_rate": "75% DELIVERED or EXCEEDED across trackable KPI-year pairs",
    "extraction_notes": "Any caveats about data quality or comparability"
  }
}
```

**Key rules for the JSON:**
- `"not_reported"` string (not null) when a previously-tracked KPI is absent — the absence is data
- `value` is always numeric (float or int), never a string with units
- `yoy_change` is a string like "+18.0%" or "-5.2%" or null if prior year not available
- `mgmt_tone` captures how management framed this number: "positive", "negative", "neutral", "defensive"
- `core_kpis` = count of KPIs reported in >50% of available years

#### 6B: Longitudinal Summary Markdown

Save to: `data/kpi_database/{TICKER}_kpi_summary.md`

```markdown
# {TICKER} — Operational KPI Database | {earliest FY} to {latest FY}

| Field | Value |
|---|---|
| Company | {Full name} |
| Industry | {industry} |
| Years Covered | {N} years ({earliest} to {latest}) |
| Total KPIs Tracked | {N} |
| Core KPIs (>50% years) | {N} |
| Last Updated | {date} |

## Core Operational KPIs (Longitudinal)

{For each core KPI, build a year-by-year table}

### {Category Name}

| KPI | {FY1} | {FY2} | ... | {FYn} | Trend | CAGR |
|---|---|---|---|---|---|---|
| {label} | {val} | {val} | ... | {val} | {trend} | {cagr} |

## Newly Discovered KPIs (Latest Year Only)

{KPIs that appeared for the first time in the most recent extraction — these may become core KPIs if management continues reporting them}

| KPI | Value | Category | Source Block |
|---|---|---|---|

## Discontinued KPIs

{KPIs that were reported in prior years but NOT in the latest year}

| KPI | Last Reported | Last Value | Possible Reason |
|---|---|---|---|

## KPI Consistency Matrix

{Visual matrix showing which KPIs were reported in which years}

| KPI | {FY1} | {FY2} | ... | {FYn} | Consistency |
|---|---|---|---|---|---|
| {label} | ✓ | ✓ | — | ✓ | 3/4 |

## Management Integrity — Stated vs Achieved

**Delivery Scorecard:** {X} DELIVERED / {Y} PARTIALLY / {Z} MISSED / {W} ABANDONED out of {total} trackable KPI-year pairs | **Delivery Rate: {pct}%**

### Full Tracker

| KPI | FY Stated | What Management Said | FY Checked | What Happened | Verdict |
|---|---|---|---|---|---|
| {label} | FY{N-1} | "{verbatim or paraphrased claim}" | FY{N} | {actual value + YoY} | DELIVERED |
| {label} | FY{N-1} | "{claim}" | FY{N} | {actual} | MISSED |

### Integrity Patterns

{3-5 bullet points highlighting:}
- Are quantified commitments more reliable than qualitative ones?
- Which categories does management consistently deliver on vs consistently miss?
- Any pattern of over-promising in good years and under-delivering in bad years?
- Silent abandonment: commitments that disappeared without acknowledgment

## Signals & Observations

{3-5 bullet points highlighting:}
- Which KPIs management is MOST consistent about (these are their true north stars)
- Any KPIs that appeared/disappeared (signals strategic pivot or obfuscation)
- Cross-KPI correlations (e.g., order book growth leading revenue growth by 1 year)
- Metrics where management tone shifted despite stable numbers (or vice versa)
```

---

## Guidelines

1. **Management chooses what to highlight.** What they report IS the signal. What they stop reporting is also a signal.
2. **Consistency > comprehensiveness.** A KPI reported 6/6 years is infinitely more valuable than one reported 1/6 years. Weight core KPIs heavily.
3. **Preserve management's language.** If they say "Order Booking" not "new orders received", use their term. This makes the database searchable against the source documents.
4. **Numbers only in the database.** Narratives go in the markdown summary. The JSON must be machine-queryable — no prose in value fields.
5. **YoY context matters.** A metric's value without its YoY change loses half its meaning. Always compute and store the change.
6. **Don't over-extract.** If a number appears once in passing ("we have 12 warehouses"), it's not a KPI unless management tracks it year over year. Use the longitudinal check to separate signal from noise.
7. **Segment data is high-value.** Revenue by segment, geography, product type, customer type — these splits reveal business model evolution even when total revenue looks smooth.

---

## File Contract

```
Input:
    data/annual_reports/{TICKER}/{TICKER}_MDA_*context.md    ← Source MDA files

Output:
    data/kpi_database/{TICKER}.json                          ← Structured KPI database
    data/kpi_database/{TICKER}_kpi_summary.md                ← Human-readable longitudinal view
```
