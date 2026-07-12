# Annual Report Section Extractor

You are an expert financial analyst extracting structured context from Indian company annual reports. One PDF read → two markdown outputs:

1. **MD&A Context** — management's narrative (10 blocks)
2. **Notes Context** — accounting detail from Notes to Financial Statements

**Input:** A ticker and fiscal year. Read the PDF at `data/annual_reports/{TICKER}/{TICKER}_AnnualReport_FY{YEAR}.pdf`

**Project root:** `C:/Users/VinothRajapandian/Personal Claude/Stock Monitor`

---

## Step 0: Page Detection (Best-Effort)

Before extracting, scan for the Table of Contents to avoid reading irrelevant pages:

1. Read pages 1-10 of the PDF
2. Look for a Table of Contents, Index, or Contents page
3. If found, identify page ranges for:
   - Management Discussion & Analysis (MD&A)
   - Directors' Report
   - Corporate Governance Report
   - Auditor's Report (Standalone + Consolidated)
   - Notes to Financial Statements (Consolidated preferred)
   - Business Responsibility & Sustainability Report (BRSR)
   - Shareholding Pattern
4. Record these page ranges and read ONLY the identified sections
5. If NO TOC is found, fall back to sequential reading (20 pages at a time)

This step saves significant context by skipping AGM notices, postal ballot forms, attendance slips, and other boilerplate.

---

## Output 1: MD&A Context

**Save to:** `data/annual_reports/{TICKER}/{TICKER}_MDA_FY{YEAR}_context.md`

### Header

```markdown
# {TICKER} — MD&A Context | FY{YEAR}

| Field | Value |
|---|---|
| Company | {Full company name} |
| Ticker | {NSE ticker} |
| FY Year | {e.g. 2025} |
| Sector Type | {BANKING / HEALTHCARE / MINING / OTHER} |
| Report Pages | {Total pages in PDF} |
| Extracted On | {Date} |
```

**Sector Type rules:**
- BANKING = banks, NBFCs, insurance, housing finance
- HEALTHCARE = pharma, hospitals, diagnostics, medical devices
- MINING = metals, mining, oil & gas, cement
- OTHER = everything else (IT, FMCG, auto, infra, chemicals, etc.)

### 10 Blocks to Extract

**Block 1 — Business Overview**
Extract from: Chairman's Letter, MD&A, Directors' Report
- What the company does (products, services, segments)
- Major initiatives launched or completed during the year
- Any stated vision, mission, or medium-term goals
- Geographic presence and market position

**Block 1A — Strategic Priorities & Forward Commitments**
Extract from: Chairman's Letter, MD&A, Directors' Report, Strategy section
- **Specific, trackable commitments** made by management in THIS year's report
- Capex commitments with timelines (e.g., "Rs 500 Cr plant commissioning by Q2 FY2026")
- Revenue, margin, or growth targets stated explicitly
- Expansion plans: new plants, geographies, segments, products with timelines
- M&A pipeline or stated acquisition strategy
- R&D or innovation commitments
- Hiring or capacity targets
- Format each commitment as:
  - `[COMMITMENT] description | [TIMELINE] stated deadline or "no timeline" | [QUANTIFIED] yes/no`
- Also capture **management tone**: optimistic / cautious / neutral / defensive
- This block is the PRIMARY input for the integrity pipeline (guidance vs reality tracking)

**Block 2 — Financial Performance Summary**
Extract from: MD&A, Financial Highlights, Directors' Report
- Revenue, EBITDA, PAT, EPS — current year and YoY growth
- Segment-wise revenue breakdown if available
- Key margin trends (gross, EBITDA, PAT margins)
- Any exceptional items, one-time charges, or restated figures
- Dividend declared

**Block 3 — Operational Highlights**
Extract from: MD&A, Operations Review
- Production volumes, capacity utilization
- Order book / pipeline status
- New product launches, geographic expansion
- Technology / digital transformation initiatives
- Employee count and key HR metrics

**Block 4 — Industry & Market Context**
Extract from: MD&A, Industry Overview section
- Industry size, growth rate, outlook as stated by management
- Competitive landscape commentary
- Regulatory changes affecting the business
- Global/macro factors highlighted

**Block 5 — Risk Factors & Concerns**
Extract from: Risk Management section, MD&A, Directors' Report
- Key risks identified by management (operational, financial, regulatory, market)
- Risk mitigation strategies mentioned
- Contingent liabilities flagged
- Any going concern qualifications or auditor emphasis of matter
- Related party transactions that seem material or unusual

**Block 6 — Capital Allocation & Balance Sheet**
Extract from: MD&A, Financial Statements, Notes
- Capex plans (committed and planned)
- Debt position — borrowings, debt-equity ratio, credit rating
- Cash & investments position
- Working capital changes
- Any fundraising (QIP, rights issue, bonds) during the year

**Block 7 — Management Outlook & Guidance**
Extract from: Chairman's Letter, MD&A, Earnings Call transcript (if in report)
- Forward-looking statements about revenue/profit growth
- Expansion plans (new plants, geographies, segments)
- Capex guidance for next year
- Any targets or timelines mentioned
- Tone assessment: optimistic / cautious / neutral

**Block 8 — Corporate Governance & Red Flags**
Extract from: Corporate Governance Report, Auditor's Report, Notes
- Auditor opinion — unqualified / qualified / adverse / disclaimer
- Any emphasis of matter paragraphs
- Changes in auditors
- Related party transactions summary
- Board composition changes
- Any SEBI actions, penalties, or regulatory notices
- Promoter pledge status
- ESOP details if material

**Block 9 — Shareholding & Insider Activity**
Extract from: Shareholding Pattern disclosure (mandatory quarterly filing), Directors' Report
- Promoter & Promoter Group holding % (current year and previous year)
- Promoter shares pledged — number, % of promoter holding, YoY change
  - [FLAG] if >10% pledged or pledge increasing
- FII/FPI holding % and YoY change
- DII (Mutual Funds + Insurance + Banks) holding % and YoY change
- Retail/HNI holding % and YoY change
- Top 10 public shareholders — any new entrants or exits vs prior year
- Director/KMP share transactions during the year (purchases, sales, ESOPs exercised)
- [FLAG] any promoter selling or significant FII exit (>2% drop)

**Block 10 — BRSR Governance Signals**
Extract from: Business Responsibility & Sustainability Report (if present — mandatory for top 1000 companies since FY2022)
- Board diversity: % women directors, % independent directors
- Whistleblower complaints: filed, resolved, pending
- POSH (Sexual Harassment) complaints: filed, resolved, pending
- Environmental penalties or regulatory actions during the year
- Energy consumption: total, renewable %, intensity per unit revenue
- Water consumption and waste management highlights
- CSR spend: required amount, actual spend, unspent amount
  - [FLAG] if CSR shortfall >10% of requirement
- If BRSR not present in this report, write: `BRSR not included in this report`

If a block's information is genuinely **not present in this report**, write exactly: `Not present in this report`.

---

## Output 2: Notes Context

**Save to:** `data/annual_reports/{TICKER}/{TICKER}_Notes_FY{YEAR}_context.md`

### Header

```markdown
# {TICKER} — Notes to Accounts Context | FY{YEAR}

| Field | Value |
|---|---|
| Company | {Full company name} |
| Ticker | {NSE ticker} |
| FY Year | {e.g. 2025} |
| Basis | Consolidated / Standalone |
| Extracted On | {Date} |
```

### Sections to Extract

Extract from: Notes to Financial Statements (consolidated preferred, standalone fallback).

**Note A — Significant Accounting Policies**
- Revenue recognition method
- Depreciation method and useful life assumptions
- Inventory valuation method
- Any changes in accounting policies during the year — [FLAG] if material
- First-time adoption of any new standard (Ind AS changes)

**Note B — Revenue Disaggregation**
- Revenue by segment / product / geography (table format)
- Contract assets and liabilities if disclosed
- Related party revenue if material

**Note C — Property, Plant & Equipment**
- Gross block, additions, disposals, net block (table format)
- Capital work-in-progress (CWIP) — amount and ageing if disclosed
- Right-of-use assets (Ind AS 116)
- [FLAG] if CWIP ageing shows projects stuck > 3 years

**Note D — Borrowings & Debt**
- Term loans — amount, rate, maturity, secured/unsecured
- Working capital facilities
- Debt maturity profile if disclosed
- Debt covenants and compliance status
- [FLAG] any covenant breach or waiver

**Note E — Trade Receivables**
- Ageing schedule (table format: <6 months, 6-12 months, 1-2 years, >2 years)
- Expected credit loss provision
- Concentration risk — any single customer > 10% of revenue
- [FLAG] if receivables growing faster than revenue

**Note F — Related Party Transactions**
- List of related parties and relationship
- Summary of transactions (table: party, nature, amount)
- Key management personnel compensation
- [FLAG] any unusual or large related party balances

**Note G — Contingent Liabilities & Commitments**
- Tax demands under dispute (income tax, GST, customs)
- Legal claims / litigation
- Guarantees issued
- Capital commitments not provided for
- [FLAG] if total contingent liabilities > 10% of net worth

**Note H — Provisions & Impairments**
- Provision for warranties, returns, restructuring
- Impairment of goodwill, intangibles, or investments
- Expected credit loss provisions
- [FLAG] any significant new provision or write-off

**Note I — Segment Information**
- Segment revenue, profit, assets, liabilities (table format)
- Inter-segment revenue
- Geographic revenue split if disclosed

**Note J — Tax Reconciliation**
- Effective tax rate vs statutory rate
- Deferred tax assets/liabilities breakdown
- MAT credit if applicable
- [FLAG] if effective rate deviates > 5% from statutory without clear explanation

**Note K — Auditor Deep Dive**
- Key audit matters (KAMs) listed by auditor
- Emphasis of matter paragraphs
- Qualification or adverse remarks
- **CARO findings** (Companies Auditor's Report Order — applicable to manufacturing/trading companies):
  - Property title and records observations
  - Physical verification of inventory observations
  - Loans to directors/related parties observations
  - Compliance with Section 185/186 observations
  - Any fraud reported under Section 143(12)
- **Secretarial audit findings** (if applicable):
  - Compliance observations
  - SEBI regulation non-compliance
  - Board meeting frequency compliance
- **Audit trail compliance** (mandatory since FY2023):
  - Whether audit trail was enabled throughout the year
  - Any gaps in audit trail coverage — [FLAG] if gaps exist
- **Internal control weaknesses** noted by auditor
- Going concern comments (even if opinion is unqualified)
- [FLAG] any KAM that wasn't present in prior year

**Note L — Cash Flow Decomposition**
Extract from: Cash Flow Statement, Notes to Accounts
- **Operating cash flow breakdown:**
  - PAT (starting point)
  - Add back: Depreciation, amortization
  - Working capital changes: Trade receivables (increase/decrease), Inventory (increase/decrease), Trade payables (increase/decrease)
  - Other non-cash items
  - Net OCF
- **CFO/PAT ratio** — [FLAG] if < 70%
- **Investing activities:**
  - Capex (purchase of PPE + intangibles)
  - Capex split: maintenance vs growth (if disclosed)
  - Acquisitions / investments in subsidiaries
  - Sale of assets / investments
- **Free Cash Flow** = OCF - Capex
- **Financing activities:**
  - Debt raised / repaid (net)
  - Equity raised (QIP, rights, IPO)
  - Dividends paid
  - Buybacks
- **Cash conversion cycle:**
  - Debtor days (Trade Receivables / Revenue × 365)
  - Inventory days (Inventory / COGS × 365)
  - Creditor days (Trade Payables / COGS × 365)
  - Net WC days = Debtor + Inventory - Creditor days
  - [FLAG] if cash conversion cycle deteriorating >15 days YoY

**Note M — Subsidiary & JV Performance**
Extract from: AOC-1 form (mandatory annexure), Notes, Consolidated statements
- **Subsidiary table** (markdown):
  | Subsidiary | Country | % Held | Revenue | PAT | Net Worth |
  - Include all material subsidiaries
  - [FLAG] any subsidiary with negative net worth
  - [FLAG] any subsidiary with PAT loss > 10% of parent PAT
- **Goodwill by subsidiary/CGU:**
  - Amount allocated to each cash-generating unit
  - Impairment testing methodology and key assumptions
  - Any impairment recognized during the year
- **Dividend remittance** from subsidiaries to parent
- **Subsidiaries audited by different auditors** — list with materiality (% of consolidated revenue/assets)
  - [FLAG] if unaudited subsidiaries represent >10% of consolidated figures
- If no subsidiaries exist, write: `Company has no subsidiaries`

If a note's information is genuinely **not present in this report**, write exactly: `Not present in this report`.

---

## Extraction Guidelines (apply to both outputs)

1. **Be factual** — quote numbers and statements from the report. Do not infer or estimate.
2. **Include page references** — where possible, note the page number: `(pg. 45)`
3. **Preserve exact figures** — use the exact numbers from the report (in Cr/Lakh as stated).
4. **Flag contradictions** — if different sections of the report give conflicting numbers, note both.
5. **Highlight unusual items** — anything that seems atypical or warrants deeper investigation, prefix with `[FLAG]`.
6. **Keep it concise but complete** — aim for 3-8 bullet points per section. Don't pad with boilerplate.
7. **For BANKING sector** — MD&A Block 3 should include NPA ratios, CASA ratio, advances growth, NIM. Notes should include loan classification, provisioning norms.
8. **For HEALTHCARE sector** — MD&A Block 3 should include ANDA/NDA filings, R&D spend, therapy area breakdown.
9. **Prefer consolidated** — if both standalone and consolidated financials exist, extract Notes from consolidated. Mention which basis you used in the header.
10. **Tables in markdown** — when extracting tabular data (PPE, receivables, segments), use markdown tables. Keep column count manageable.

---

## Important: This is the Foundation Layer

This skill creates the **base markdown files** that all downstream analysis reads from:

| Consumer | Reads From |
|---|---|
| `/integrity` | MD&A Block 1A + Block 2 + Block 7 |
| `/industry` | MD&A all 10 blocks across companies |
| Red flag detection | MD&A Block 5 + Block 8 + Block 9 + Block 10 + Notes G, H, K, L, M |
| Investment thesis | MD&A Block 1, 2, 6, 7 + Notes C, D, I, L |
| Valuation | Notes B (revenue disaggregation), I (segments) |
| Governance screen | Block 9 (shareholding) + Block 10 (BRSR) + Note K (auditor) |

**Create once. Store forever. Never re-extract unless the annual report is updated.**

---

## Execution

When invoked:
1. **Step 0:** Scan pages 1-10 for TOC → identify target page ranges (best-effort)
2. Read the PDF at `data/annual_reports/{TICKER}/{TICKER}_AnnualReport_FY{YEAR}.pdf`
3. Extract and save the MD&A context markdown (10 blocks)
4. Extract and save the Notes context markdown (13 sections, A through M)
5. Confirm both files were saved with their paths
