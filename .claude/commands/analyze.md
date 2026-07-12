# Company Analysis Orchestrator

You are the master orchestrator for a full investment deep dive on an Indian listed company. This skill runs the complete 9-step pipeline, calling individual skills in sequence, and produces a comprehensive integrated report.

**Input:** User provides a ticker (e.g., `ACE`, `ECOSMOBLTY`). Optionally a year range for annual reports (default: last 5 years).

**Project root:** `C:/Users/VinothRajapandian/Personal Claude/Stock Monitor`

---

## Pipeline Overview

| Step | What | Skill/Command | Output |
|---|---|---|---|
| 1 | Fetch screener data | `python run.py monitor --test` | `data/ticker_excels/<TICKER>.xlsx` |
| 2 | Quantitative analysis | `/past-performance` + `/valuation` | `output/quality_reports/<TICKER>.md` |
| 3 | Verdict & entry point | — | Thesis saved to memory |
| 4 | Annual reports & extraction | `/extract-sections` | MDA + Notes context files |
| 5 | Management integrity | `/integrity` | Integrity report |
| 6 | Red flag (13-test forensic) | `/red-flag` | `output/red_flag/<TICKER>_red_flag.md` |
| 7 | KPI extraction | `/extract-kpis` | `data/kpi_database/<TICKER>.json` |
| 8 | Industry context | Check existing or extract from MDA Block 4 | Industry section |
| 9 | Integrated report + tracker | — | `output/quality_reports/<TICKER>_integrated.md` + tracker update |

Maps to the **5 Pointer Framework**: Valuation (Step 2), Past Performance (Step 2), Management (Step 5), Red Flag (Step 6), Industry (Step 8) — plus KPIs (Step 7) as the operational depth layer.

---

## Execution Flow

### Step 1: Fetch Screener Data

```bash
cd "C:/Users/VinothRajapandian/Personal Claude/Stock Monitor" && python run.py monitor --test <TICKER>
```

Generates `data/ticker_excels/<TICKER>.xlsx`. If the file already exists and is recent (< 7 days old), skip this step.

### Step 2: Quantitative Fundamental Analysis

Read the ticker Excel and build a quality assessment report covering:
- Key ratios (ROCE, ROE, D/E, PE, dividend yield, promoter holding)
- Growth profile (5Y/3Y/10Y Sales and PAT CAGR, acceleration/deceleration)
- Quality signals (OPM avg/range/trend, CFO/OP ratio, debtor days, working capital, tax stability)
- Incremental ROCE calculation
- Forward-looking 5Y and 10Y projections (bear/base/bull EPS and stock price)
- Quality score and verdict (HIGHEST QUALITY / HIGH QUALITY / QUALITY / WATCHLIST / AVOID)

Save to: `output/quality_reports/<TICKER>.md`

### Step 3: Verdict & Entry Point

Provide a clear verdict with accumulation zone. Auto-save the thesis to memory (per feedback rule — never ask, just save).

### Step 4: Annual Reports & Section Extraction

Download annual reports:
```bash
cd "C:/Users/VinothRajapandian/Personal Claude/Stock Monitor" && python run.py redflag-download -c <TICKER> --from-year <Y>
```

Then run `/extract-sections <TICKER> FY{YEAR}` for each year that doesn't already have context files.

This produces the **foundation layer**:
- `data/annual_reports/<TICKER>/<TICKER>_MDA_FY{YEAR}_context.md` (10 blocks)
- `data/annual_reports/<TICKER>/<TICKER>_Notes_FY{YEAR}_context.md` (13 sections, A-M)

**Do not proceed to Steps 5-7 without these files.** They are required inputs for integrity, red flag, and KPI extraction.

### Step 5: Management Integrity Analysis

Run `/integrity <TICKER>` or:
```bash
cd "C:/Users/VinothRajapandian/Personal Claude/Stock Monitor" && python run.py integrity <TICKER>
```

Requires multi-year MDA context files (from Step 4). Tracks:
- Promise vs delivery across years
- Guidance consistency
- Narrative shifts and tone changes
- Strategic commitment follow-through

If only 1 year of MDA exists (e.g., recently IPO'd company), note the limitation but still extract what's available from that single year.

### Step 6: Red Flag Analysis

Run `/red-flag <TICKER>` — the full 13-test forensic framework:

| # | Test |
|---|---|
| 1 | Revenue vs Receivables Divergence |
| 2 | Inventory Build-Up |
| 3 | Cash Flow vs Profit Divergence |
| 4 | Other Income Dependency |
| 5 | Borrowings Trajectory |
| 6 | Working Capital Deterioration |
| 7 | Related Party Transactions |
| 8 | Contingent Liabilities |
| 9 | Auditor Signals |
| 10 | Promoter & Ownership Signals |
| 11 | Subsidiary & Off-Balance-Sheet Risks |
| 12 | Q4 Loading & Quarterly Pattern |
| 13 | Management Compensation |

Requires both MDA and Notes context files from Step 4.

Output: `output/red_flag/<TICKER>_red_flag.md` + archived copy at `data/red_flag/<TICKER>/`

### Step 7: KPI Extraction

Run `/extract-kpis <TICKER>`

Reads all MDA context files and discovers operational KPIs organically — metrics management highlights that aren't in the ticker Excel (ARPOB, order book, capacity utilization, market share, export mix, etc.).

Output: `data/kpi_database/<TICKER>.json` + `<TICKER>_kpi_summary.md`

Then rebuild the SQLite database:
```bash
cd "C:/Users/VinothRajapandian/Personal Claude/Stock Monitor" && python data/kpi_database/build_db.py
```

### Step 8: Industry Context

1. **Check for existing industry report** at `data/annual_reports/industry_context/{sector_slug}.md`
2. **If found:** Pull relevant insights into the integrated report:
   - Market size & growth trajectory
   - Competitive positioning of this company vs peers
   - Policy tailwinds/risks
   - Moat assessment from sector perspective
3. **If NOT found:** Extract a lightweight industry view from the company's own MDA Block 4 covering:
   - Industry size & growth rate as stated by management
   - Competitive landscape and company's positioning
   - Key demand drivers and tailwinds
   - Regulatory/policy context
   - Risks and headwinds

Full cross-company `/industry` analysis is run separately — not part of this per-company pipeline.

### Step 9: Integrated Report & Tracker Update

#### 9A: Build Integrated Report

Combine all prior steps into a single investor-grade report at `output/quality_reports/<TICKER>_integrated.md`:

```markdown
# {TICKER} — Integrated Investment Report

**Date:** {date} | **CMP:** Rs {price} | **MCap:** {mcap} Cr | **PE:** {pe}x | **Sector:** {sector}

---

## VERDICT: {HOLD / BUY / WATCHLIST / AVOID} — {one-line rationale}

{3-5 sentence executive summary integrating all dimensions}

---

## Part 1: Quantitative Quality Assessment (Score: X/17)
{From Step 2 — key metrics, what earned/lost the score, incremental ROCE}

## Part 2: Forward Projections
{From Step 2 — bear/base/bull 5Y and 10Y EPS and price scenarios}

## Part 3: Business Model & Industry Context
{From Step 8 — competitive position, market structure, moat assessment}
{From Step 7 — key operational KPIs and trends}

## Part 4: Management & Governance Deep Dive
{From Step 5 — integrity findings, promise vs delivery}
{Auditor quality, promoter remuneration, RPTs, capital allocation}

## Part 5: Red Flag Analysis
{From Step 6 — 13-test summary table + detailed findings}
{Pattern analysis — correlated signals}

## Part 6: Integrated Verdict
{Bull case, bear case, entry strategy, key monitor items}
{Final integrated score across all dimensions}
```

#### 9B: Update Analysis Tracker

Update `output/analysis_tracker.html`:
- Find or add the ticker's entry in the `const data = [...]` JavaScript array
- Set/update: `redFlags` (e.g. "4/13 MINOR"), `redFlagVerdict` (clear/minor/material/dealbreaker)
- Add ALL report links: Integrated, Red Flag, Integrity, Quant
- Update `rationale` to include red flag summary AND integrity verdict
- Update `date` to today

#### 9C: Save Thesis to Memory

Auto-save/update the thesis memory at `memory/project_{ticker_lower}_watchlist.md` with:
- Verdict, quality score, key metrics
- Red flag summary (flag count, verdict, key concerns)
- Governance assessment highlights
- Entry/accumulation zone
- Key monitor items

#### 9D: Generate X Thread

Auto-generate a 5-tweet story arc thread and save to `output/x_threads/{TICKER}_thread.md`. User posts to X manually.

**Thread structure (each tweet under 280 chars, plain text + emojis, no markdown):**

| Tweet | Section | Content |
|---|---|---|
| 1 | Hook | Verdict emoji + most compelling, non-obvious angle. Frame as a STORY — what's the tension, the surprise, the contrarian take? End with "A thread" + thread emoji. |
| 2 | Numbers | Key financials: quality score, ROCE, OPM, PE, debt, yield, MCap. Add one non-obvious metric. |
| 3 | Management | Strategic guidance vs reality. Integrity score. What did management promise? What did they deliver? What's the gap? Focus on CREDIBILITY, not red flags. |
| 4 | Risk | Red flag score + severity. Top 2-3 specific concerns with numbers. Promoter/FII signals if notable. |
| 5 | Verdict | BUY/HOLD/AVOID + accumulation zone + CMP vs zone. Forward return. End with "Not investment advice. DYOR." + #StockAnalysis #IndianStocks |

**Verdict emojis:** BUY = green circle, HOLD/WATCHLIST = yellow circle, AVOID = red circle, AVOID HIGH CONVICTION = rotating light

---

## Execution Rules

1. **Always run Steps 1-3** for any company analysis request.
2. **Always run Steps 4-9** when the user requests individual company analysis — no quality score gate.
3. The score >= 10 gate only applies during **batch screening** (e.g., small-cap quality screen) where running deep dives on every company is impractical.
4. **Never skip steps or change the order.** Each step's output feeds the next.
5. If a step fails (e.g., annual reports not available, integrity requires multi-year data), note the limitation and continue with remaining steps.
6. **Foundation layer is non-negotiable:** Do not run Steps 5-7 without MDA/Notes context files from Step 4.

---

## File Contract

```
Input:
    data/ticker_excels/{TICKER}.xlsx                                    ← Step 1

Foundation Layer (Step 4):
    data/annual_reports/{TICKER}/{TICKER}_AnnualReport_FY{YEAR}.pdf     ← Downloaded
    data/annual_reports/{TICKER}/{TICKER}_MDA_FY{YEAR}_context.md       ← Extracted
    data/annual_reports/{TICKER}/{TICKER}_Notes_FY{YEAR}_context.md     ← Extracted

Analysis Outputs:
    output/quality_reports/{TICKER}.md                                  ← Step 2
    output/red_flag/{TICKER}_red_flag.md                                ← Step 6
    data/red_flag/{TICKER}/{TICKER}_red_flag_FY{YEAR}.md                ← Step 6 (archive)
    data/kpi_database/{TICKER}.json                                     ← Step 7
    data/kpi_database/{TICKER}_kpi_summary.md                           ← Step 7

Final Output:
    output/quality_reports/{TICKER}_integrated.md                       ← Step 9A
    output/analysis_tracker.html                                        ← Step 9B (updated)
    output/x_threads/{TICKER}_thread.md                                 ← Step 9D
```
