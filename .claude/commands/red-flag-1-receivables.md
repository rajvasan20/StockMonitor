# Red Flag Sub-Skill 1: Revenue Recognition & Receivables Forensics

You are running a deep forensic analysis on revenue quality and receivables for an Indian listed company. This is not a surface scan — you are looking for the story the numbers tell when read together, and if flags exist, you will drill to root cause using the 5 Whys framework.

**Input:** User provides a ticker (e.g., `BAJAJ-AUTO`) and optionally a year range.

**Project root:** `C:/Users/VinothRajapandian/Personal Claude/Stock Monitor`

---

## Data Sources

Load these in order. **All are required.**

### 1. Excel Financial Data
`data/ticker_excels/{TICKER}.xlsx`
- **Profit & Loss** — Revenue, Other Operating Revenue, Other Income (10-year)
- **Balance Sheet** — Trade Receivables, Loans & Advances, Unbilled Revenue (10-year)
- **Ratios** — Debtor Days (10-year)
- **Quarterly** — Last 12-14 quarters (revenue and receivables if available)

### 2. Notes to Accounts (All Available Years)
`data/annual_reports/{TICKER}/{TICKER}_Notes_*FY{YEAR}*.md`
- **Note A** — Revenue Recognition Policy (exact policy language, any changes)
- **Note B** — Revenue Disaggregation (segment-wise, geography-wise, contract vs recognized)
- **Note E** — Trade Receivables (ageing schedule, ECL provision, concentration)
- **Note F** — Related Party Transactions (are receivables from related parties?)

If Notes files don't exist, **STOP and tell the user to run `/extract-sections` first.** This analysis requires Notes data.

---

## Analysis Framework (7 Layers)

### Layer 1: Revenue Growth Quality
Assess whether revenue growth is real, sustainable, and cash-backed.

**Compute:**
- Revenue CAGR (3-year, 5-year, 10-year)
- Year-on-year revenue growth rate for each year
- Organic vs inorganic: did revenue jump coincide with acquisitions?
- Revenue mix stability: are segments shifting? Is a declining segment being masked by a growing one?

**From Notes (Note B):**
- Revenue disaggregation by segment and geography — is growth concentrated in one segment/geography or broad-based?
- Contracted price vs recognized revenue — is the gap (discounts, incentives) widening?
- Other operating revenue as % of total revenue — is it growing? What's in it?

**Key question:** Is the company growing because customers are buying more, or because accounting is doing heavy lifting?

---

### Layer 2: Revenue Recognition Policy Forensics
The most important 2 paragraphs in any annual report.

**From Notes (Note A) across all available years:**
- Extract exact revenue recognition policy language for each year
- **Diff the policy year-over-year** — any wording change, no matter how subtle, is a signal
- Check: point-in-time vs over-time recognition — which method and why?
- Check: bill-and-hold arrangements — revenue recognized before delivery?
- Check: long-term contracts — percentage of completion vs completed contract method?
- Check: channel incentives — netted against revenue or expensed separately?

**Specific tests:**
- [FLAG] Any revenue recognition policy change during the analysis period
- [FLAG] Policy allows revenue recognition before delivery/acceptance
- [FLAG] Policy is vague or uses non-standard language
- [FLAG] Adoption of new accounting standards led to material revenue restatement

**Key question:** Has the company changed HOW it counts revenue to make the number look better?

---

### Layer 3: Receivables Trajectory Analysis
The core quantitative test — but done properly this time.

**Compute (annual, all available years):**
- Trade receivables absolute value
- Receivables growth rate vs revenue growth rate (the divergence ratio)
- Debtor days (from Ratios sheet + cross-verify by computing from B/S and P&L)
- Receivables as % of revenue (the receivable intensity ratio)

**Build the divergence table:**
| Year | Revenue (Cr) | Rev Growth % | Receivables (Cr) | Recv Growth % | Divergence Ratio | Debtor Days | Recv/Revenue % |
|---|---|---|---|---|---|---|---|

**Specific tests:**
- [FLAG] Receivables growth > 1.5x revenue growth for 2+ consecutive years
- [FLAG] Debtor days increased > 15 days over 3 years
- [FLAG] Debtor days increased > 30 days over 5 years
- [FLAG] Receivables/Revenue ratio increased by > 3 percentage points over analysis period
- [FLAG] Sudden spike in receivables in any single year (> 2x prior year)

**Key question:** Is the company selling to customers who can't or won't pay?

---

### Layer 4: Receivables Ageing Deep Dive
The ageing schedule is the X-ray of receivables quality.

**From Notes (Note E) across all available years:**
- Extract full ageing table for each year
- Compute % distribution across ageing buckets (< 6 months, 6m-1y, 1-2y, 2-3y, > 3y)
- Track how each bucket's share changes over time

**Build the ageing evolution table:**
| Year | < 6 months % | 6m-1y % | 1-2y % | 2-3y % | > 3y % | Total (Cr) |
|---|---|---|---|---|---|---|

**Specific tests:**
- [FLAG] > 3 year bucket exceeds 5% of total receivables
- [FLAG] Any ageing bucket > 6 months growing as % of total over consecutive years
- [FLAG] Fresh receivables (< 6 months) declining as % of total — old stuff piling up
- [FLAG] Total receivables growing while fresh receivables flat = only old stuff accumulating

**ECL (Expected Credit Loss) Provision Analysis:**
- ECL provision as % of gross receivables — is it adequate?
- ECL provision rate vs actual write-offs — is the company under-provisioning?
- [FLAG] ECL provision < 1% when > 3 year receivables exist
- [FLAG] ECL provision declining while old receivables growing
- [FLAG] Zero or near-zero ECL provision with receivables > 3 years (RAJESHEXPO pattern)

**Key question:** Are old receivables being kept alive on the books to avoid profit hits?

---

### Layer 5: Receivables Concentration & Related Party Check
Who owes the money matters as much as how much is owed.

**From Notes (Note E & Note F):**
- Does the company disclose customer concentration in receivables?
- Are any receivables from related parties? If yes, what % of total?
- Cross-reference RPT note: do related party sales correspond to related party receivables?
- Government vs private receivables split (if available) — government receivables are slower but safer

**Specific tests:**
- [FLAG] Related party receivables > 10% of total receivables
- [FLAG] Related party receivables growing faster than third-party receivables
- [FLAG] Single customer/group > 25% of total receivables (concentration risk)
- [FLAG] Receivables from entities in the promoter group
- [FLAG] Standalone receivables that don't eliminate on consolidation = external exposure disguised as intra-group or vice versa

**Key question:** Is the company lending to itself through the receivables line?

---

### Layer 6: Quarterly Revenue Pattern Analysis
Quarterly data reveals what annual data hides.

**From Quarterly sheet (last 12-14 quarters):**
- Revenue by quarter — compute Q4 as % of full year revenue
- Quarter-over-quarter sequential growth rates
- Is there a hockey stick pattern? (weak Q1-Q3, strong Q4)

**Specific tests:**
- [FLAG] Q4 revenue > 30% of annual revenue for 2+ consecutive years (channel stuffing signal)
- [FLAG] Q4 revenue spike followed by Q1 revenue dip (stuffing + returns pattern)
- [FLAG] Revenue acceleration in Q4 with margin compression = discounting to hit targets
- [FLAG] Sequential revenue decline for 3+ quarters masked by a strong Q4

**Key question:** Is the company front-loading or back-loading revenue to manage earnings?

---

### Layer 7: Cash Conversion Cross-Check
Revenue is an opinion. Cash is a fact.

**From P&L and Cash Flow:**
- Revenue vs cash collected from operations (CFO before working capital changes is proxy)
- Trade receivables change as % of revenue change — when revenue goes up by 100, how much sits in receivables?
- CFO/Revenue ratio trend over analysis period

**Specific tests:**
- [FLAG] Revenue grew but CFO declined in same year (paper revenue)
- [FLAG] > 30% of incremental revenue stuck in receivables for 2+ years
- [FLAG] CFO/Revenue ratio declining over 3+ years while revenue growing

**Key question:** Is revenue converting to cash, or just to receivables?

---

## 5 Whys Protocol (Triggered When Flags Found)

If **3 or more flags** are raised across the 7 layers, activate the 5 Whys drill-down. This is not optional.

For each cluster of related flags, ask 5 progressive "Why" questions using the data:

```
WHY 1: What does the data show? (State the flag with exact numbers)
WHY 2: What could cause this? (List 2-3 hypotheses — benign and malicious)
WHY 3: What evidence supports or eliminates each hypothesis? (Cross-reference across layers)
WHY 4: What is the most likely explanation? (Converge on the diagnosis)
WHY 5: What would confirm or deny this diagnosis? (What to watch going forward)
```

The 5 Whys must use **verbatim data** from the analysis — no vague speculation. Each "Why" must cite specific numbers, years, or note references.

---

## Output Format

Save to: `output/red_flag/{TICKER}_rf1_receivables.md`

```markdown
# {TICKER} — Revenue & Receivables Forensics

| Field | Value |
|---|---|
| Company | {Full name} |
| Ticker | {NSE ticker} |
| Period | FY{FROM} to FY{TO} ({N} years) |
| Analysis Date | {date} |
| Data Sources | {list Excel sheets and Notes files used} |

---

## Key Takeaways

{5-7 bullet points. Each bullet is one insight — not a restatement of a metric, but a PERSPECTIVE on what the metric means. Lead with the conclusion, support with the number.}

Example format:
- **Revenue growth is real but slowing** — 10Y CAGR of 18% masks deceleration from 25% (FY15-20) to 11% (FY20-25)
- **Receivables are clean** — 94% under 6 months, debtor days stable at 28-32 range, no ageing deterioration
- **Q4 loading is within normal bounds** — Q4 contributes 27-29% of annual revenue, consistent with industry seasonality

---

## Layer 1: Revenue Growth Quality
{Bullet-format findings with data tables where needed}

## Layer 2: Revenue Recognition Policy
{Bullet-format findings — exact policy quotes with year-over-year diff}

## Layer 3: Receivables Trajectory
{Divergence table + bullet findings}

## Layer 4: Receivables Ageing
{Ageing evolution table + ECL analysis + bullet findings}

## Layer 5: Concentration & Related Party
{Bullet findings with specific RPT cross-references}

## Layer 6: Quarterly Patterns
{Q4 loading analysis + sequential trends + bullet findings}

## Layer 7: Cash Conversion
{CFO cross-check + bullet findings}

---

## Flag Summary

| Layer | Flags | Key Flag |
|---|---|---|
| 1. Revenue Growth | {count} | {worst flag or "CLEAR"} |
| 2. Rev Rec Policy | {count} | {worst flag or "CLEAR"} |
| 3. Receivables Trajectory | {count} | {worst flag or "CLEAR"} |
| 4. Receivables Ageing | {count} | {worst flag or "CLEAR"} |
| 5. Concentration/RPT | {count} | {worst flag or "CLEAR"} |
| 6. Quarterly Patterns | {count} | {worst flag or "CLEAR"} |
| 7. Cash Conversion | {count} | {worst flag or "CLEAR"} |
| **Total** | **{N}** | |

---

## 5 Whys Root Cause Analysis
{Only if 3+ flags. One 5-Why chain per cluster of related flags.}

### Chain 1: {Name the pattern}
- **WHY 1:** {data}
- **WHY 2:** {hypotheses}
- **WHY 3:** {evidence test}
- **WHY 4:** {diagnosis}
- **WHY 5:** {confirmation test}

### Chain 2: ...

---

## Verdict

**{CLEAN / WATCH / CONCERN / SEVERE}**

| Verdict | Criteria |
|---|---|
| CLEAN | 0-2 flags, no patterns, receivables well-managed |
| WATCH | 3-4 flags, isolated issues, no correlated pattern |
| CONCERN | 5-7 flags or any correlated pattern across layers |
| SEVERE | 8+ flags, correlated patterns, or any evidence of revenue manipulation |

{3-5 sentences. Perspective, not just summary. What does this mean for an investor?}

### What to Monitor
{2-3 specific metrics or disclosures to watch in the next annual report}
```

---

## Guidelines

1. **Perspectives, not metrics.** Every bullet must answer "so what?" — a number without interpretation is noise.
2. **Cross-layer correlation is the skill.** The value of this analysis is connecting dots across all 7 layers. Layer 3 alone is what the old red-flag did. The magic is in Layer 3 + Layer 4 + Layer 5 + Layer 7 read together.
3. **Benign explanations first.** Always consider the innocent explanation before the sinister one. Industry context matters — a construction company will have different receivable patterns than an FMCG company.
4. **Verbatim evidence only.** Every flag must cite specific numbers from Excel or specific text from Notes.
5. **5 Whys is the depth mechanism.** Don't stop at "receivables are growing." Ask why until you hit a root cause or an unanswerable question (which itself is a flag).
6. **Year-over-year policy diffs matter more than the policy itself.** A company with aggressive rev rec that's been consistent for 10 years is less concerning than one that just changed its policy.
7. **Absence of disclosure = flag.** If a company doesn't provide ageing, doesn't break out receivables by type, or doesn't discuss ECL methodology — that omission is itself suspicious.

---

## File Contract

```
Input:
    data/ticker_excels/{TICKER}.xlsx                                 <- Financial data
    data/annual_reports/{TICKER}/{TICKER}_Notes_*FY{YEAR}*.md        <- Required (Notes A, B, E, F)

Output:
    output/red_flag/{TICKER}_rf1_receivables.md                      <- Final analysis
```
