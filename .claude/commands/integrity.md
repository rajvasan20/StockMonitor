# Management Integrity Agent

You are orchestrating a deep management integrity analysis for an Indian listed company. The goal: determine whether this management team is trustworthy, competent, and aligned with minority shareholders — by comparing what they promised vs what they delivered, tracking their strategic commitments, analyzing insider behavior, and calibrating their communication tone across years.

**Input:** User provides a ticker (e.g., `TCS`) and optionally a year range.

**Project root:** `C:/Users/VinothRajapandian/Personal Claude/Stock Monitor`

---

## Orchestration Flow

Execute these steps in order. Each step produces files that the next step reads. **Do not skip steps.**

### Step 1: Download Annual Reports

Run:
```bash
cd "C:/Users/VinothRajapandian/Personal Claude/Stock Monitor" && python -c "
from red_flag.downloader import run
run(companies=['{TICKER}'], from_year={FROM_YEAR}, to_year={TO_YEAR})
"
```

This downloads PDFs to `data/annual_reports/{TICKER}/`. Skip years that already have PDFs.

### Step 2: Create MD&A Context Files (Foundation Layer)

Check which years have the structured 8-block markdown:
- Look for `data/annual_reports/{TICKER}/{TICKER}_MDA_*FY{YEAR}*.md`

For each **missing** year:
1. Read the annual report PDF at `data/annual_reports/{TICKER}/{TICKER}_AnnualReport_FY{YEAR}.pdf`
2. Follow the `/extract-sections` skill instructions exactly — extract all 8 blocks into structured markdown
3. Save to: `data/annual_reports/{TICKER}/{TICKER}_MDA_FY{YEAR}_context.md`

**This is the foundation layer.** These files persist forever and are reused by `/industry`, investment thesis, red flags, and all other downstream analysis.

### Step 3: Extract Guidance + Actuals (Expanded)

For each year in the range, check if these files exist:
- `data/integrity/{TICKER}/guidance/{TICKER}_guidance_FY{YEAR}.json`
- `data/integrity/{TICKER}/actuals/{TICKER}_actuals_FY{YEAR}.json`

For each **missing** year, read the MD&A context file and extract:

**From Block 7 (Management Outlook & Guidance):**
```json
{
    "has_quantitative_target": true/false,
    "revenue_guidance": {
        "stated_target": "exact text if given, e.g. '15-20% revenue growth'" or null,
        "target_low_pct": number or null,
        "target_high_pct": number or null
    },
    "margin_guidance": {
        "stated_target": "exact text if given, e.g. 'maintain 25% EBITDA margin'" or null,
        "target_metric": "OPM/EBITDA/NPM" or null,
        "target_value_pct": number or null
    },
    "capex_guidance": {
        "stated_target": "exact text if given, e.g. 'Rs 500 Cr capex planned'" or null,
        "target_value_cr": number or null
    },
    "qualitative_outlook": "one sentence summary of growth outlook",
    "key_growth_drivers": ["driver1", "driver2"],
    "source_quotes": ["verbatim quote with (pg. XX) ref", "another quote"],
    "tone": "AGGRESSIVE/OPTIMISTIC/BALANCED/CAUTIOUS/DEFENSIVE"
}
```

**Tone definitions:**
- AGGRESSIVE = bold targets, multiple quantified commitments, confident language
- OPTIMISTIC = positive outlook but fewer hard targets
- BALANCED = acknowledges risks alongside opportunities
- CAUTIOUS = hedged language, few commitments, macro uncertainty emphasis
- DEFENSIVE = explaining misses, blaming external factors

**From Block 2 (Financial Performance Summary):**
```json
{
    "revenue_cr": number or null,
    "revenue_growth_pct": number or null,
    "pat_cr": number or null,
    "ebitda_margin_pct": number or null,
    "opm_pct": number or null,
    "capex_cr": number or null
}
```

**Rules:**
- Extract only what is explicitly stated. Do not infer.
- source_quotes must be verbatim, including page references.
- If no quantitative target exists, `has_quantitative_target = false`.

Save guidance JSON + markdown and actuals JSON + markdown using the storage helpers:
```python
from management_integrity.analyzer import store_guidance, store_actuals, _ensure_dirs
from config import INTEGRITY_DIR
from pathlib import Path

base_dir = _ensure_dirs("{TICKER}")
store_guidance(base_dir, "{TICKER}", {YEAR}, guidance_dict)
store_actuals(base_dir, "{TICKER}", {YEAR}, actuals_mda_dict, screener_dict_or_none)
```

### Step 4: Extract & Track Strategic Commitments

This is the deepest layer of integrity analysis. It goes beyond "did revenue meet guidance?" to ask: **did management deliver on the specific things they said they would do?**

**4a. Check for existing commitment files:**
- Look for `data/annual_reports/{TICKER}/{TICKER}_Commitments_FY{YEAR}.md`

**4b. For each missing year**, run the `/extract-commitments` skill:
- Read the annual report PDF
- Extract all forward-looking commitments across 10 categories: Revenue/Growth, Margin, Capex, Expansion, M&A, R&D, Debt/Balance Sheet, Operational, Shareholder Returns, ESG
- Save to: `data/annual_reports/{TICKER}/{TICKER}_Commitments_FY{YEAR}.md`

**4c. Build the Commitment Tracker:**

For each commitment from FY{N-1}, check the FY{N} actuals (from MD&A Block 2, Block 3, or Block 6):

```markdown
| FY Made | Commitment | Category | Quantified? | FY Checked | Outcome | Verdict |
|---|---|---|---|---|---|---|
| FY2022 | "Rs 500 Cr capex for new plant" | Capex | Yes | FY2023 | Actual capex Rs 480 Cr | DELIVERED |
| FY2022 | "Enter API segment" | Expansion | No | FY2023 | No API orders reported | MISSED |
| FY2023 | "25% EBITDA margin target" | Margin | Yes | FY2024 | EBITDA margin 23% | PARTIALLY |
```

**Verdict logic per commitment:**
- `DELIVERED` — outcome matches or exceeds the commitment
- `PARTIALLY` — directionally correct but fell short of target
- `MISSED` — commitment clearly not met
- `ABANDONED` — commitment not mentioned in subsequent reports, silently dropped
- `IN PROGRESS` — multi-year commitment still within stated timeline
- `NOT TRACKABLE` — commitment too vague to verify

**4d. Compute Commitment Scorecard:**
- Total commitments tracked across all years
- Delivery rate: % DELIVERED or PARTIALLY of total trackable commitments
- Miss rate: % MISSED or ABANDONED
- Quantified commitment ratio: % of commitments that had specific numbers

### Step 5: Promoter & Insider Behavior

Read the **Shareholding** sheet from `data/ticker_excels/{TICKER}.xlsx` and MD&A Block 9 (Shareholding) where available.

Analyze:
- **Promoter holding trend** — stable, increasing, or declining over the analysis period?
- **Promoter pledge trend** — any pledging? Is it increasing or decreasing?
- **FII/DII trend** — are sophisticated institutional investors adding or exiting?
- **Sell-while-talking-up detection** — cross-reference: did promoter holding decline in quarters where management tone was AGGRESSIVE or OPTIMISTIC? This is the most damning signal.
- **Insider transactions** — any block/bulk deals by promoters or KMP during the period? (from Block 9 if available)

**Classification:**
- **Aligned** — promoter holding stable or increasing, no pledges, institutions adding
- **Neutral** — no significant changes, minor fluctuations within 1-2%
- **Concerning** — promoter selling while talking up stock, pledges increasing, institutions exiting
- **Red Flag** — significant promoter dilution (>5% decline), heavy pledging (>30% pledged), insiders dumping

### Step 6: Per-Year Commentary (Expanded)

For each comparison year (FY{N} where guidance comes from FY{N-1}):
- Compare FY{N-1} guidance vs FY{N} actuals (revenue, margin, capex)
- Compare FY{N-1} strategic commitments vs FY{N} outcomes
- Note tone from FY{N-1} and whether results justified it

Write commentary to `data/integrity/{TICKER}/commentary/{TICKER}_compare_FY{YEAR}.md`:

```markdown
# {Company} — Guidance vs Reality | FY{YEAR}
**Guidance from:** FY{YEAR-1} Annual Report
**Actuals from:** FY{YEAR} Annual Report + Screener.in

## Revenue Guidance vs Actual
- Guided: {target}
- Actual: Rs X Cr (+Y% YoY)
- **Verdict: {MET/EXCEEDED/MISSED/UNQUANTIFIED}**

## Margin Guidance vs Actual
- Guided: {target}
- Actual: {X}%
- **Verdict: {MET/EXCEEDED/MISSED/UNQUANTIFIED}**

## Strategic Commitments from FY{YEAR-1}
| # | Commitment | Outcome | Verdict |
|---|---|---|---|
| 1 | {commitment} | {what happened} | {DELIVERED/PARTIALLY/MISSED/ABANDONED} |

## Management Tone (FY{YEAR-1}): {AGGRESSIVE/OPTIMISTIC/BALANCED/CAUTIOUS/DEFENSIVE}
{Was the tone justified by FY{YEAR} results?}

## Overall Year Verdict: {MET/EXCEEDED/MISSED/UNQUANTIFIED}
{2-3 sentence commentary}
```

**Verdict logic:**
- `MET` — actual growth within guided range
- `EXCEEDED` — actual growth above high end of range
- `MISSED` — actual growth below low end of range
- `UNQUANTIFIED` — no quantitative guidance was given

### Step 7: Tone Calibration

Build a cross-year tone analysis. This reveals whether management communicates honestly or always talks up the stock.

| FY Report | Tone | Revenue Growth Next FY | Key Prediction | Outcome | Tone Justified? |
|---|---|---|---|---|---|
| FY2020 | OPTIMISTIC | +X% | "strong recovery" | {what happened} | Yes/No |
| FY2021 | AGGRESSIVE | +X% | "record order book" | {what happened} | Yes/No |

Analyze:
- **Tone accuracy score:** What % of years had tone justified by subsequent results?
- **Perpetual optimist?** Is tone always OPTIMISTIC/AGGRESSIVE regardless of results? This signals management is in PR mode, not communicating honestly.
- **Defensive pattern:** Does management blame external factors (commodity prices, COVID, policy changes) when results miss, but take full credit when results are good?
- **Tone-to-action gap:** Does management change strategy after a miss, or just keep repeating the same guidance?

### Step 8: Pattern Assessment & Integrity Verdict

After all years are processed, write the multi-dimensional integrity assessment:

**Dimension 1: Guidance Accuracy**
- How many years was guidance met/exceeded vs missed?
- Track record: E (exceeded), M (met), X (missed), U (unquantified)
- Example: "3E/1M/0X across 4 quantified years"

**Dimension 2: Strategic Delivery**
- Commitment delivery rate across all trackable commitments
- Pattern: does management over-commit or under-commit?
- Silent abandonments: how many commitments were quietly dropped?

**Dimension 3: Communication Quality**
- Tone calibration score
- Does management communicate risks honestly?
- Are they forthcoming about failures or do they bury them?

**Dimension 4: Insider Alignment**
- Promoter behavior classification
- Insider buying/selling pattern
- Institutions voting with their feet?

**Overall Integrity Verdict:**
- **HIGH INTEGRITY** — guidance mostly met/exceeded, commitments delivered, honest communication, aligned insiders
- **ADEQUATE** — mixed track record, some misses acknowledged, no red flags
- **CONCERNING** — pattern of over-promising, silent abandonments, defensive communication, or insider misalignment
- **LOW INTEGRITY** — serial over-promiser, commitments routinely missed/abandoned, insiders selling while talking up

### Step 9: Assemble Final Report

Run:
```bash
cd "C:/Users/VinothRajapandian/Personal Claude/Stock Monitor" && python run.py integrity {TICKER} --from-year {FROM_YEAR} --to-year {TO_YEAR}
```

If the assembler script doesn't support the expanded format, write the final report manually with this structure:

```markdown
# {TICKER} — Management Integrity Analysis | FY{FROM}-FY{TO}

| Field | Value |
|---|---|
| Company | {Full name} |
| Ticker | {NSE ticker} |
| Period | FY{FROM} to FY{TO} ({N} years) |
| Analysis Date | {date} |

## Integrity Scorecard

| Dimension | Classification | Key Evidence |
|---|---|---|
| Guidance Accuracy | {E/M/X summary} | {one-line} |
| Strategic Delivery | {X}% delivery rate | {one-line} |
| Communication Quality | {Honest/PR Mode/Defensive} | {one-line} |
| Insider Alignment | {Aligned/Neutral/Concerning/Red Flag} | {one-line} |
| **Overall Verdict** | **{HIGH INTEGRITY / ADEQUATE / CONCERNING / LOW INTEGRITY}** | |

## 1. Guidance vs Reality (Year-by-Year)

### FY{YEAR}: {VERDICT}

| Metric | Guided | Actual | Verdict |
|---|---|---|---|
| Revenue Growth | {X}% | {X}% | {MET/EXCEEDED/MISSED} |
| Margin ({metric}) | {X}% | {X}% | {MET/EXCEEDED/MISSED} |
| Capex | Rs {X} Cr | Rs {X} Cr | {MET/EXCEEDED/MISSED} |

{2-3 sentence commentary}

{Repeat for each year}

### Guidance Track Record Summary

| FY Guided | FY Checked | Revenue | Margin | Capex | Tone | Overall |
|---|---|---|---|---|---|---|
| FY{N-1} | FY{N} | {E/M/X/U} | {E/M/X/U} | {E/M/X/U} | {tone} | {verdict} |

## 2. Strategic Commitment Tracker

| FY Made | Commitment | Category | Quantified? | FY Checked | Outcome | Verdict |
|---|---|---|---|---|---|---|
{All commitments across all years}

### Commitment Scorecard
- Total commitments tracked: {N}
- Delivered: {N} ({X}%)
- Partially delivered: {N} ({X}%)
- Missed: {N} ({X}%)
- Abandoned: {N} ({X}%)
- Not trackable: {N}

{3-5 sentences. Is management a reliable executor? Do they over-commit? How many commitments were silently dropped?}

## 3. Promoter & Insider Behavior

| Quarter | Promoter % | Change | FII % | DII % | Public % |
|---|---|---|---|---|---|

- Promoter trend: {stable/increasing/declining} — {start}% to {end}% over {period}
- Pledge status: {none/declining/increasing/critical}
- FII trend: {adding/stable/exiting}
- Sell-while-talking-up: {none detected / {specific instances}}
- **Classification: {Aligned/Neutral/Concerning/Red Flag}**

{3-5 sentences. Are insiders aligned with minority shareholders?}

## 4. Tone Calibration

| FY Report | Tone | Result Next FY | Tone Justified? |
|---|---|---|---|
| FY{N} | {tone} | {what happened} | {Yes/No} |

- Tone accuracy: {X}% of years had tone justified by results
- Pattern: {Honest communicator / Perpetual optimist / Defensive when failing / Balanced}
- Tone-to-action gap: {Does management adjust strategy after misses?}

{3-5 sentences. Does management communicate honestly with shareholders?}

## 5. Integrity Verdict

**{HIGH INTEGRITY / ADEQUATE / CONCERNING / LOW INTEGRITY}**

{5-7 sentences. Lead with the overall judgment. Then strongest evidence for/against. What discount should an investor apply to forward guidance from this management? End with: "An investor relying on management's forward statements should apply a {X}% credibility haircut."}

### The Management Story in One Paragraph
{Single paragraph narrating the management's behavior pattern over the analysis period — not just guidance accuracy, but the full picture of how they communicate, commit, and behave as stewards of shareholder capital.}
```

### Step 10: Output Structured Guidance Tracker JSON

After the narrative report is complete, serialize the Promise vs Delivery table into a structured JSON file for cross-linking with the KPI database.

Save to: `data/guidance_tracker/{TICKER}_guidance.json`

```json
{
  "ticker": "{TICKER}",
  "company": "{Full company name}",
  "last_updated": "{ISO date}",
  "integrity_score": "{X}/20",
  "integrity_verdict": "{HIGH INTEGRITY / ADEQUATE / CONCERNING / LOW INTEGRITY}",
  "delivery_summary": {
    "total_commitments": 18,
    "delivered": 10,
    "partially": 3,
    "missed": 2,
    "abandoned": 1,
    "in_progress": 1,
    "not_trackable": 1,
    "delivery_rate_pct": 72
  },
  "commitments": [
    {
      "id": 1,
      "year_made": "FY2022",
      "commitment": "Rs 500 Cr capex for new plant in Sanand",
      "category": "capex",
      "quantified": true,
      "timeline": "FY2023",
      "year_checked": "FY2023",
      "outcome": "Actual capex Rs 480 Cr; Sanand Phase 1 commissioned",
      "verdict": "DELIVERED",
      "kpi_link": "capex_annual",
      "evidence_source": "Block 2, Block 6"
    },
    {
      "id": 2,
      "commitment": "FMCG-Others margin improvement to 10%+",
      "year_made": "FY2023",
      "category": "margin",
      "quantified": true,
      "timeline": "FY2024-FY2025",
      "year_checked": "FY2025",
      "outcome": "Margin compressed from 10.2% to 7.2%",
      "verdict": "MISSED",
      "kpi_link": "fmcg_others_ebitda_margin",
      "evidence_source": "Block 3"
    }
  ]
}
```

**Schema rules:**
- `category`: One of `revenue`, `margin`, `capex`, `expansion`, `m_and_a`, `r_and_d`, `debt`, `operational`, `shareholder_returns`, `esg`
- `verdict`: One of `DELIVERED`, `EXCEEDED`, `PARTIALLY`, `MISSED`, `ABANDONED`, `IN_PROGRESS`, `NOT_TRACKABLE`
- `kpi_link`: The KPI key from `data/kpi_database/{TICKER}.json` that this commitment maps to. Use `null` if no KPI tracks this commitment (e.g., qualitative commitments like "enter new geography"). **Check the KPI JSON for exact key names before assigning.**
- `delivery_rate_pct`: `(delivered + partially) / (total - not_trackable - in_progress) * 100`
- Sort commitments by `year_made` ascending, then by `id`

**Cross-linking with KPI database:**
When a commitment maps to a KPI (e.g., "grow order book to Rs 15,000 Cr" → `order_booking`), the `kpi_link` creates a bridge. This allows downstream tools to:
1. Show the commitment alongside the KPI's actual trajectory
2. Validate whether the KPI's `stated` field (from `/extract-kpis` Step 3B) aligns with this commitment
3. Build a unified "what management said vs what happened" view

---

## Defaults

- `FROM_YEAR`: current year - 5
- `TO_YEAR`: current year
- Ticker must be in the NIFTY 50 + EXTRA_TICKERS registry in `red_flag/downloader.py`

---

## Guidelines

1. **Extract only what is explicitly stated.** Do not infer guidance from revenue trends. If management didn't give a number, mark it UNQUANTIFIED.
2. **Silent abandonments are the worst signal.** A commitment that simply disappears from future reports — never acknowledged as missed, never updated — is worse than an honest miss.
3. **Tone must be calibrated against results, not intentions.** An "AGGRESSIVE" tone followed by 5% growth is a credibility failure.
4. **Promoter behavior speaks louder than chairman's letter.** If management is selling shares while publishing "bullish outlook", the shares tell the truth.
5. **One year doesn't make a pattern.** A single miss with honest explanation is forgivable. A pattern of misses with defensive explanations is damning.
6. **Cross-reference everything.** Guidance from Block 7, actuals from Block 2 + Screener data, commitments from Block 1A, behavior from Shareholding. No single source tells the full story.

---

## File Contract

```
Input:
    data/annual_reports/{TICKER}/
        {TICKER}_AnnualReport_FY{YEAR}.pdf              ← Step 1 (downloader)
        {TICKER}_MDA_FY{YEAR}_context.md                ← Step 2 (mda-context)
        {TICKER}_Commitments_FY{YEAR}.md                ← Step 4 (extract-commitments)
    data/ticker_excels/{TICKER}.xlsx                     ← Shareholding sheet (Step 5)

Intermediate:
    data/integrity/{TICKER}/
        guidance/{TICKER}_guidance_FY{YEAR}.json         ← Step 3
        guidance/{TICKER}_guidance_FY{YEAR}.md           ← Step 3
        actuals/{TICKER}_actuals_FY{YEAR}.json           ← Step 3
        actuals/{TICKER}_actuals_FY{YEAR}.md             ← Step 3
        commentary/{TICKER}_compare_FY{YEAR}.md          ← Step 6
        {TICKER}_integrity_report.md                     ← Step 9 (archived)

Output:
    output/integrity_reports/{TICKER}_integrity.md       ← Step 9 (final)
    data/guidance_tracker/{TICKER}_guidance.json          ← Step 10 (structured)
```
