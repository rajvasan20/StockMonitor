"""X/Twitter Thread Generator — 5-Tweet Story Arc from Thesis Memory.

Converts investment thesis memory files into a 5-tweet thread:
    Tweet 1: Hook — compelling story angle + verdict
    Tweet 2: The Numbers — ROCE, OPM, growth, cash flow
    Tweet 3: The Risk — red flags + integrity score
    Tweet 4: The Context — industry position, competitive edge
    Tweet 5: The Verdict — BUY/HOLD/AVOID + accumulation zone

Each tweet stays within 280 characters.

Usage:
    from x_poster.thread_generator import generate_thread
    thread = generate_thread("TECHM")
"""

import os
import re
import glob

from shared.utils import logger

# Memory directory for thesis files
MEMORY_DIR = os.path.join(
    os.path.expanduser("~"),
    ".claude",
    "projects",
    "C--Users-VinothRajapandian-Personal-Claude-Stock-Monitor",
    "memory",
)


def _find_thesis_file(ticker: str) -> str | None:
    """Find the memory thesis file for a ticker."""
    pattern = os.path.join(MEMORY_DIR, "project_*_watchlist.md")
    for filepath in glob.glob(pattern):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        # Match ticker in the content (first bold line usually has TICKER)
        if re.search(rf'\b{ticker}\b', content, re.IGNORECASE):
            return filepath
    return None


def _parse_thesis(filepath: str) -> dict:
    """Parse a thesis memory file into structured fields."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Strip YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            body = parts[2].strip()
        else:
            frontmatter = ""
            body = content
    else:
        frontmatter = ""
        body = content

    # Extract description from frontmatter
    desc_match = re.search(r'description:\s*(.+)', frontmatter)
    description = desc_match.group(1).strip() if desc_match else ""

    # Extract verdict (BUY/HOLD/AVOID/WATCHLIST)
    # Check multiple patterns — explicit verdict line first, then header, then description
    verdict = "WATCHLIST"
    # Pattern 1: **Verdict:** BUY or Verdict: BUY
    verdict_match = re.search(
        r'(?:\*\*)?Verdict(?:\*\*)?[:\s]+(?:\*\*)?(?:BUY|HOLD|AVOID|WATCHLIST)\b',
        body, re.IGNORECASE
    )
    if verdict_match:
        v = re.search(r'(BUY|AVOID|HOLD|WATCHLIST)', verdict_match.group(0), re.IGNORECASE)
        if v:
            verdict = v.group(1).upper()
    else:
        # Pattern 2: "— BUY thesis" or "| WATCHLIST**" in header
        header_verdict = re.search(r'[—|]\s*(BUY|AVOID|HOLD|WATCHLIST)\b', body, re.IGNORECASE)
        if header_verdict:
            verdict = header_verdict.group(1).upper()
        else:
            # Pattern 3: from description frontmatter
            desc_verdict = re.search(r'\b(BUY|AVOID)\b', description)
            if desc_verdict:
                verdict = desc_verdict.group(1).upper()

    # Detect HIGH CONVICTION qualifier
    high_conviction = "HIGH CONVICTION" in body.upper()

    # Extract company name and ticker from first bold line or ## header
    # Formats: **TECHM — Tech Mahindra Ltd | WATCHLIST**
    #          **TCS (Tata Consultancy Services)** — BUY thesis
    #          ## NCC LIMITED — AVOID HIGH CONVICTION (8/17)
    #          **CMP:** Rs 154 (NCC has CMP as first bold)
    ticker_in_body = ""
    company_name = ""

    # Try ## header format first
    hdr_match = re.search(r'^##\s+(.+?)(?:\s*—|\s*$)', body, re.MULTILINE)
    # Try **NAME** format
    name_match = re.search(r'\*\*([A-Z][^*]+?)\s*(?:\(([^)]+)\))?\*\*\s*(?:—|$)', body, re.MULTILINE)

    if name_match:
        raw_name = name_match.group(1).strip()
        # Parse "TICKER — Company Name | VERDICT" or "Company Name"
        parts = re.split(r'\s*[—|]\s*', raw_name)
        if len(parts) >= 2:
            ticker_in_body = parts[0].strip()
            company_name = parts[1].strip()
        else:
            company_name = parts[0].strip() if parts else ""
        # Also check parentheses format: **TCS (Tata Consultancy Services)**
        if name_match.group(2):
            company_name = name_match.group(2).strip()
            if not ticker_in_body:
                ticker_in_body = parts[0].strip() if parts else ""
    elif hdr_match:
        raw_name = hdr_match.group(1).strip()
        # "NCC LIMITED" — extract ticker as first word
        words = raw_name.split()
        if words:
            ticker_in_body = words[0].strip()
            company_name = raw_name

    # Extract CMP — handles **CMP:** Rs 154 and CMP: Rs 1,450
    cmp_match = re.search(r'\*{0,2}CMP:?\*{0,2}:?\s*(?:Rs\s*)?[\u20b9]?\s*([\d,]+)', body)
    cmp = cmp_match.group(1).replace(",", "") if cmp_match else ""

    # Extract PE — handles **PE:** 13.8x and PE: 28.5x
    pe_match = re.search(r'\*{0,2}PE:?\*{0,2}:?\s*([\d.]+)x', body)
    pe = pe_match.group(1) if pe_match else ""

    # Extract MCap — handles **MCap:** Rs 9,643 Cr
    mcap_match = re.search(r'\*{0,2}MCap:?\*{0,2}:?\s*(?:Rs\s*)?[\u20b9]?\s*([\d,]+)\s*Cr', body)
    mcap = mcap_match.group(1).replace(",", "") if mcap_match else ""

    # Extract quality score — handles "Quant 15/17", "**Quality Score:** 12/17", "(8/17)"
    qs_match = re.search(r'(?:Quality Score|Quant)[\s:*]*(\d+)/(\d+)', body)
    if not qs_match:
        # Try from header: "## NCC LIMITED — AVOID HIGH CONVICTION (8/17)"
        qs_match = re.search(r'\((\d+)/(\d+)\)', body)
    quality_score = f"{qs_match.group(1)}/{qs_match.group(2)}" if qs_match else ""

    # Extract ROCE — handles ROCE: 16.8% and ROCE 23.1%
    roce_match = re.search(r'ROCE[\s:*]*([\d.]+)%', body)
    roce = roce_match.group(1) if roce_match else ""

    # Extract OPM — handles OPM: 16% and OPM 8-12%
    opm_match = re.search(r'OPM[\s:*]*([\d.]+)%', body)
    opm = opm_match.group(1) if opm_match else ""

    # Extract D/E
    de_match = re.search(r'D/E[\s:*]*([\d.]+)', body)
    de = de_match.group(1) if de_match else ""

    # Extract dividend yield
    yield_match = re.search(r'(?:Yield|dividend yield)[\s:*]*([\d.]+)%', body, re.IGNORECASE)
    div_yield = yield_match.group(1) if yield_match else ""

    # Extract Red Flags line
    rf_match = re.search(r'Red Flags?[:\s]*(\d+/\d+)\s*(\w+(?:\s+\w+)?)', body, re.IGNORECASE)
    red_flag_score = rf_match.group(1) if rf_match else ""
    red_flag_severity = rf_match.group(2) if rf_match else ""

    # Extract red flag details
    rf_details = []
    # Try structured format (### Red Flags followed by bullet list)
    rf_section = re.search(
        r'(?:###\s*Red Flags?)[^\n]*\n((?:[-*]\s+.+\n?)+)',
        body, re.IGNORECASE
    )
    if rf_section:
        rf_details = [
            line.strip().lstrip("-* ").strip()
            for line in rf_section.group(1).strip().split("\n")
            if line.strip().startswith(("-", "*"))
        ]
    else:
        # Compact format: **Red Flags:** 3/13 MINOR. Detail1, detail2...
        rf_inline = re.search(
            r'\*\*Red Flags?:\*\*\s*\d+/\d+\s*\w+[\w\s]*?[.—]\s*(.+?)(?:\n\*\*|\n-\s+\*\*|$)',
            body, re.DOTALL
        )
        if rf_inline:
            detail_text = rf_inline.group(1).strip()
            # Split on major separators (period followed by capital, or semicolons)
            rf_details = [s.strip().rstrip(".") for s in re.split(r'(?<=\.)\s+(?=[A-Z])|;\s*', detail_text) if s.strip() and len(s.strip()) > 15]

    # Extract Integrity score
    int_match = re.search(r'Integrity[:\s]*(\d+/\d+)\s*(\w+(?:\s+\w+)?)', body, re.IGNORECASE)
    integrity_score = int_match.group(1) if int_match else ""
    integrity_label = int_match.group(2) if int_match else ""

    # Extract integrity details
    int_details = []
    int_section = re.search(
        r'(?:###\s*Integrity)[^\n]*\n((?:[-*]\s+.+\n?)+)',
        body, re.IGNORECASE
    )
    if int_section:
        int_details = [
            line.strip().lstrip("-* ").strip()
            for line in int_section.group(1).strip().split("\n")
            if line.strip().startswith(("-", "*"))
        ]
    else:
        # Compact format: **Integrity:** score — details
        int_inline = re.search(
            r'\*\*Integrity:\*\*\s*\d+/\d+\s*\w+[\w\s]*?[.—]\s*(.+?)(?:\n\*\*|\n-\s+\*\*|$)',
            body, re.DOTALL
        )
        if int_inline:
            int_details = [int_inline.group(1).strip()[:120]]

    # Extract Thesis narrative
    thesis_match = re.search(r'\*\*Thesis:\*\*\s*(.+?)(?:\n\n|\n\*\*)', body, re.DOTALL)
    thesis_narrative = thesis_match.group(1).strip() if thesis_match else ""

    # Also check for Verdict line that contains the thesis
    if not thesis_narrative:
        verdict_line = re.search(r'\*\*Verdict:\*\*\s*(?:BUY|HOLD|AVOID|WATCHLIST)[^.]*\.\s*(.+?)(?:\n\n|\n\*\*)', body, re.DOTALL | re.IGNORECASE)
        if verdict_line:
            thesis_narrative = verdict_line.group(1).strip()

    # Extract turnaround/key thesis from bullet points
    turnaround_match = re.search(r'\*\*Turnaround thesis:\*\*\s*(.+?)(?:\n-\s+\*\*|\n\*\*|$)', body, re.DOTALL)
    turnaround = turnaround_match.group(1).strip() if turnaround_match else ""
    if turnaround and not thesis_narrative:
        thesis_narrative = turnaround
    elif turnaround:
        thesis_narrative = thesis_narrative + " " + turnaround

    # Extract accumulation zone — handles **Accumulation zone:** Rs 1,200-1,300 and similar
    acc_match = re.search(
        r'(?:Accumulation|Accumulate|Entry)[^:]*[:\s*]+\s*(?:Rs\s*)?[\u20b9]?\s*([\d,]+)\s*[-–—]\s*(?:Rs\s*)?[\u20b9]?\s*([\d,]+)',
        body, re.IGNORECASE
    )
    acc_low = acc_match.group(1).replace(",", "") if acc_match else ""
    acc_high = acc_match.group(2).replace(",", "") if acc_match else ""

    # Extract forward return
    fwd_match = re.search(r'Forward[^:]*:\s*(.+)', body, re.IGNORECASE)
    forward_return = fwd_match.group(1).strip() if fwd_match else ""

    # Extract sector — try explicit Sector: field first, then infer from description
    sector_match = re.search(r'\*{0,2}Sector:?\*{0,2}:?\s*([^\n|*]+)', body, re.IGNORECASE)
    sector = sector_match.group(1).strip() if sector_match else ""
    if not sector:
        # Infer from description frontmatter
        desc_sector = re.search(
            r'(IT services|IT company|NBFC|pharma|hospital|bank|construction|EPC|FMCG|auto software|automobile|steel|insurance|software|chemicals|energy|infra|solar|mobility|RTA|card maker)',
            description + " " + thesis_narrative[:200], re.IGNORECASE
        )
        sector = desc_sector.group(0) if desc_sector else ""

    # Extract shareholding info
    promoter_match = re.search(r'Promoter[:\s]*([\d.]+)%', body)
    promoter = promoter_match.group(1) if promoter_match else ""

    fii_match = re.search(r'FII[:\s]*([^\n,]+)', body, re.IGNORECASE)
    fii_info = fii_match.group(1).strip() if fii_match else ""

    # Extract key monitor items — handles both numbered list and inline (1) (2) format
    monitor_items = []
    # Try structured numbered list format
    monitor_section = re.search(
        r'(?:Key Monitor|Monitor Items?)[^\n]*\n((?:\d+\..+\n?)+)',
        body, re.IGNORECASE
    )
    if monitor_section:
        monitor_items = [
            re.sub(r'^\d+\.\s*', '', line.strip()).strip()
            for line in monitor_section.group(1).strip().split("\n")
            if line.strip()
        ]
    else:
        # Try compact format: **Key monitors:** (1) item, (2) item
        km_inline = re.search(
            r'\*\*Key monitors?:\*\*\s*(.+?)(?:\n|$)',
            body, re.IGNORECASE
        )
        if km_inline:
            items_text = km_inline.group(1).strip()
            # Split on (N) markers
            parts = re.split(r'\(\d+\)\s*', items_text)
            monitor_items = [p.strip().rstrip(",").strip() for p in parts if p.strip()]

    return {
        "company_name": company_name,
        "ticker_in_body": ticker_in_body,
        "description": description,
        "verdict": verdict,
        "high_conviction": high_conviction,
        "cmp": cmp,
        "pe": pe,
        "mcap": mcap,
        "quality_score": quality_score,
        "roce": roce,
        "opm": opm,
        "de": de,
        "div_yield": div_yield,
        "red_flag_score": red_flag_score,
        "red_flag_severity": red_flag_severity,
        "red_flag_details": rf_details,
        "integrity_score": integrity_score,
        "integrity_label": integrity_label,
        "integrity_details": int_details,
        "thesis_narrative": thesis_narrative,
        "acc_low": acc_low,
        "acc_high": acc_high,
        "forward_return": forward_return,
        "sector": sector,
        "promoter": promoter,
        "fii_info": fii_info,
        "monitor_items": monitor_items,
        "raw_body": body,
    }


def _generate_ai_thread(t: dict) -> list[str]:
    """Use Claude API to craft compelling 5-tweet thread from parsed thesis data.

    Falls back to template-based generation if API is unavailable.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception as e:
        logger.warning(f"Claude API unavailable ({e}). Using template fallback.")
        return _build_template_thread(t)

    ticker = t["ticker_in_body"] or t["company_name"]
    name = t["company_name"] or t["ticker_in_body"]

    system_prompt = (
        "You are a sharp, opinionated Indian equity analyst who writes viral "
        "stock analysis threads on X/Twitter. Your style: punchy, data-backed, "
        "no fluff. You write like a seasoned investor talking to friends — "
        "conversational but rigorous.\n\n"
        "RULES:\n"
        "- Each tweet MUST be under 275 characters (strict limit)\n"
        "- Use ONLY the data provided. NEVER invent numbers\n"
        "- No markdown formatting (no **, no ##). Plain text + emojis only\n"
        "- No generic lines like 'Let me explain' or 'Here's why'\n"
        "- Write in a way that makes someone stop scrolling\n"
        "- Use Rs for currency, Cr for crores, L Cr for lakh crores"
    )

    user_prompt = f"""Write a 5-tweet X/Twitter thread for {ticker} ({name}).

THESIS DATA:
{t['raw_body']}

STRUCTURE (write exactly 5 tweets separated by ===TWEET===):

Tweet 1 — THE HOOK:
Start with the verdict emoji ({_verdict_emoji(t['verdict'], t['high_conviction'])} for {t['verdict']}).
Lead with the most interesting, non-obvious angle about this company.
NOT just "OPM went up" — frame it as a STORY. What's the tension? The surprise? The contrarian take?
Examples of good hooks: "This CEO doubled margins in 8 quarters — and nobody noticed."
"The market says 14x PE is cheap. The cash flow says it's a trap."
End with "A thread" and thread emoji.

Tweet 2 — THE NUMBERS:
Start with the emoji: 📊
Key financial metrics that support the story. Quality score, ROCE, OPM, PE, debt, yield.
Add ONE non-obvious metric that makes someone think.
Format as clean lines, not a wall of text.

Tweet 3 — THE MANAGEMENT:
Start with the emoji: 🎯
Focus on STRATEGIC GUIDANCE vs REALITY. Did management deliver on promises?
Integrity score ({t['integrity_score']} {t['integrity_label']}).
What did they promise? What did they actually deliver? What's the gap?
This is about credibility, not red flags.

Tweet 4 — THE RISK:
Start with the emoji: ⚠️
Red flags ({t['red_flag_score']} {t['red_flag_severity']}).
Top 2-3 specific concerns with numbers.
Promoter holding, FII movement if noteworthy.

Tweet 5 — THE VERDICT:
Start with verdict emoji ({_verdict_emoji(t['verdict'], t['high_conviction'])} {t['verdict']}).
Accumulation zone if available: Rs {t['acc_low'] or '?'} - Rs {t['acc_high'] or '?'}.
CMP: Rs {t['cmp'] or '?'}. How far from entry zone.
Forward return if available.
End with: "Not investment advice. DYOR."
Add: #StockAnalysis #IndianStocks

CRITICAL: Each tweet must be UNDER 275 characters. Count carefully. Return ONLY the 5 tweets separated by ===TWEET=== markers."""

    logger.info(f"  Calling Claude API for {ticker} tweet thread...")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
    except Exception as e:
        logger.error(f"  Claude API call failed: {e}")
        return _build_template_thread(t)

    # Parse the 5 tweets
    tweets = [tweet.strip() for tweet in raw.split("===TWEET===") if tweet.strip()]

    # Validate and truncate if needed
    validated = []
    for i, tweet in enumerate(tweets[:5]):
        if len(tweet) > 280:
            # Truncate at last word boundary
            truncated = tweet[:277]
            last_space = truncated.rfind(" ")
            if last_space > 200:
                truncated = truncated[:last_space]
            tweet = truncated + "..."
        validated.append(tweet)

    # Pad if fewer than 5 tweets
    while len(validated) < 5:
        validated.append(f"[Tweet {len(validated)+1} generation failed]")

    return validated


def _build_template_thread(t: dict) -> list[str]:
    """Template-based fallback when Claude API is unavailable."""
    ticker = t["ticker_in_body"] or t["company_name"]
    name = t["company_name"] or t["ticker_in_body"]
    emoji = _verdict_emoji(t["verdict"], t["high_conviction"])

    tweet1 = f"{emoji} {ticker} — {name}\n\n"
    if t["thesis_narrative"]:
        first_sent = t["thesis_narrative"].split(".")[0] + "."
        tweet1 += first_sent
    tweet1 += "\n\nA thread \U0001f9f5\u2193"

    lines2 = ["\U0001f4ca THE NUMBERS\n"]
    for label, key in [("Quality", "quality_score"), ("ROCE", "roce"),
                        ("OPM", "opm"), ("PE", "pe"), ("Yield", "div_yield")]:
        if t.get(key):
            suffix = "%" if key in ("roce", "opm", "div_yield") else ("x" if key == "pe" else "")
            lines2.append(f"{label}: {t[key]}{suffix}")
    tweet2 = "\n".join(lines2)

    tweet3 = f"\U0001f3af MANAGEMENT\n\nIntegrity: {t['integrity_score']} {t['integrity_label']}"
    tweet4 = f"\u26a0\ufe0f THE RISK\n\nRed Flags: {t['red_flag_score']} {t['red_flag_severity']}"

    tweet5 = f"{emoji} VERDICT: {t['verdict']}\n"
    if t["acc_low"] and t["acc_high"]:
        tweet5 += f"Zone: Rs {int(t['acc_low']):,} - Rs {int(t['acc_high']):,}\n"
    tweet5 += "Not investment advice. DYOR.\n#StockAnalysis #IndianStocks"

    return [_truncate(tw) for tw in [tweet1, tweet2, tweet3, tweet4, tweet5]]


def _truncate(text: str, max_len: int = 280) -> str:
    """Truncate text to fit tweet limit, preserving word boundaries."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len - 1]
    last_space = truncated.rfind(" ")
    if last_space > max_len * 0.6:
        truncated = truncated[:last_space]
    return truncated + "\u2026"


def _verdict_emoji(verdict: str, high_conviction: bool = False) -> str:
    """Map verdict to emoji."""
    mapping = {
        "BUY": "\U0001f7e2",
        "HOLD": "\U0001f7e1",
        "WATCHLIST": "\U0001f7e1",
        "AVOID": "\U0001f534",
    }
    e = mapping.get(verdict.upper(), "\u26aa")
    if high_conviction and verdict.upper() == "AVOID":
        e = "\U0001f6a8"
    return e


def generate_thread(ticker: str) -> list[str] | None:
    """Generate a 5-tweet thread for a given ticker.

    Uses Claude API for compelling, story-driven tweets.
    Falls back to templates if API unavailable.

    Returns a list of 5 strings (tweets), or None if thesis not found.
    """
    filepath = _find_thesis_file(ticker)
    if not filepath:
        return None

    t = _parse_thesis(filepath)
    return _generate_ai_thread(t)


def get_all_thesis_tickers() -> list[str]:
    """Return all tickers that have thesis memory files."""
    pattern = os.path.join(MEMORY_DIR, "project_*_watchlist.md")
    tickers = []
    for filepath in glob.glob(pattern):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        # Extract ticker from the first bold line
        match = re.search(r'\*\*(\w+)\s*(?:\(|\u2014|—|\|)', content)
        if match:
            tickers.append(match.group(1).upper())
        else:
            # Try from filename
            fname = os.path.basename(filepath)
            slug = fname.replace("project_", "").replace("_watchlist.md", "")
            tickers.append(slug.upper())
    return sorted(set(tickers))


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "TECHM"
    thread = generate_thread(ticker)
    if thread:
        for i, tweet in enumerate(thread, 1):
            print(f"\n{'='*50}")
            print(f"TWEET {i} ({len(tweet)} chars)")
            print(f"{'='*50}")
            print(tweet)
    else:
        print(f"No thesis found for {ticker}")
