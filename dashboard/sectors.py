"""Sector classification for Nifty 100 stocks.

Maps each ticker to its sector and industry for sector-level analysis,
concentration checks, and heatmap rendering in the Trade Planner.
"""

SECTOR_MAP = {
    # ── Banking & Financial Services ─────────────────────────────
    "AXISBANK":     ("Banking", "Private Bank"),
    "BAJFINANCE":   ("Banking", "NBFC"),
    "BAJAJFINSV":   ("Banking", "NBFC"),
    "BANKBARODA":   ("Banking", "PSU Bank"),
    "CANBK":        ("Banking", "PSU Bank"),
    "CHOLAFIN":     ("Banking", "NBFC"),
    "HDFCBANK":     ("Banking", "Private Bank"),
    "ICICIBANK":    ("Banking", "Private Bank"),
    "INDUSINDBK":   ("Banking", "Private Bank"),
    "KOTAKBANK":    ("Banking", "Private Bank"),
    "PNB":          ("Banking", "PSU Bank"),
    "SBIN":         ("Banking", "PSU Bank"),
    "UNIONBANK":    ("Banking", "PSU Bank"),
    "POONAWALLA":   ("Banking", "NBFC"),
    "SHRIRAMFIN":   ("Banking", "NBFC"),
    "MUTHOOTFIN":   ("Banking", "NBFC"),
    "RECLTD":       ("Banking", "NBFC"),

    # ── Insurance ────────────────────────────────────────────────
    "HDFCLIFE":     ("Insurance", "Life Insurance"),
    "ICICIGI":      ("Insurance", "General Insurance"),
    "ICICIPRULI":   ("Insurance", "Life Insurance"),
    "LICI":         ("Insurance", "Life Insurance"),
    "SBICARD":      ("Insurance", "Credit Card"),
    "SBILIFE":      ("Insurance", "Life Insurance"),
    "POLICYBZR":    ("Insurance", "InsurTech"),

    # ── IT & Technology ──────────────────────────────────────────
    "HCLTECH":      ("IT", "IT Services"),
    "INFY":         ("IT", "IT Services"),
    "LT":           ("IT", "Engineering & IT"),
    "LTTS":         ("IT", "IT Services"),
    "PERSISTENT":   ("IT", "IT Services"),
    "TCS":          ("IT", "IT Services"),
    "TECHM":        ("IT", "IT Services"),
    "WIPRO":        ("IT", "IT Services"),
    "TATACOMM":     ("IT", "Telecom IT"),

    # ── Pharma & Healthcare ──────────────────────────────────────
    "APOLLOHOSP":   ("Pharma", "Hospitals"),
    "CIPLA":        ("Pharma", "Pharma"),
    "DIVISLAB":     ("Pharma", "API/CDMO"),
    "DRREDDY":      ("Pharma", "Pharma"),
    "LUPIN":        ("Pharma", "Pharma"),
    "MANKIND":      ("Pharma", "Pharma"),
    "SUNPHARMA":    ("Pharma", "Pharma"),
    "TORNTPHARM":   ("Pharma", "Pharma"),
    "ZYDUSLIFE":    ("Pharma", "Pharma"),

    # ── Auto & Auto Components ───────────────────────────────────
    "BAJAJ-AUTO":   ("Auto", "Two-Wheeler"),
    "EICHERMOT":    ("Auto", "Two-Wheeler"),
    "HEROMOTOCO":   ("Auto", "Two-Wheeler"),
    "M&M":          ("Auto", "Auto OEM"),
    "MARUTI":       ("Auto", "Auto OEM"),
    "MOTHERSON":    ("Auto", "Auto Components"),
    "TATAMTRDVR":   ("Auto", "Auto OEM"),
    "BOSCHLTD":     ("Auto", "Auto Components"),

    # ── Energy & Oil & Gas ───────────────────────────────────────
    "BPCL":         ("Energy", "Oil & Gas"),
    "GAIL":         ("Energy", "Gas Distribution"),
    "IOC":          ("Energy", "Oil & Gas"),
    "ONGC":         ("Energy", "Oil & Gas"),
    "RELIANCE":     ("Energy", "Conglomerate"),
    "ADANIGREEN":   ("Energy", "Renewable Energy"),
    "TATAPOWER":    ("Energy", "Power"),
    "NHPC":         ("Energy", "Power"),
    "NTPC":         ("Energy", "Power"),
    "POWERGRID":    ("Energy", "Power Grid"),
    "COALINDIA":    ("Energy", "Coal"),
    "ATGL":         ("Energy", "Gas Distribution"),

    # ── Metals & Mining ──────────────────────────────────────────
    "HINDALCO":     ("Metals", "Aluminium"),
    "JINDALSTEL":   ("Metals", "Steel"),
    "JSWSTEEL":     ("Metals", "Steel"),
    "TATASTEEL":    ("Metals", "Steel"),
    "VEDL":         ("Metals", "Diversified Metals"),

    # ── FMCG & Consumer ──────────────────────────────────────────
    "BRITANNIA":    ("FMCG", "Food"),
    "COLPAL":       ("FMCG", "Personal Care"),
    "GODREJCP":     ("FMCG", "Personal Care"),
    "HINDUNILVR":   ("FMCG", "FMCG"),
    "ITC":          ("FMCG", "FMCG/Tobacco"),
    "MARICO":       ("FMCG", "FMCG"),
    "NESTLEIND":    ("FMCG", "Food"),
    "TATACONSUM":   ("FMCG", "Food & Beverage"),
    "VBL":          ("FMCG", "Beverages"),
    "UNITDSPR":     ("FMCG", "Spirits"),
    "PAGEIND":      ("FMCG", "Apparel"),

    # ── Cement & Building Materials ──────────────────────────────
    "AMBUJACEM":    ("Cement", "Cement"),
    "GRASIM":       ("Cement", "Cement/Diversified"),
    "SHREECEM":     ("Cement", "Cement"),
    "ULTRACEMCO":   ("Cement", "Cement"),

    # ── Capital Goods & Industrials ──────────────────────────────
    "BEL":          ("Capital Goods", "Defence Electronics"),
    "BHEL":         ("Capital Goods", "Power Equipment"),
    "HAVELLS":      ("Capital Goods", "Electricals"),
    "SIEMENS":      ("Capital Goods", "Engineering"),
    "SUPREMEIND":   ("Capital Goods", "Plastics/Pipes"),

    # ── Infrastructure & Real Estate ─────────────────────────────
    "ADANIENT":     ("Infra", "Conglomerate"),
    "ADANIPORTS":   ("Infra", "Ports"),
    "DLF":          ("Infra", "Real Estate"),
    "IRCTC":        ("Infra", "Railways/Tourism"),

    # ── Telecom ──────────────────────────────────────────────────
    "BHARTIARTL":   ("Telecom", "Telecom"),

    # ── Retail & Consumer Discretionary ──────────────────────────
    "TITAN":        ("Retail", "Jewellery"),
    "TRENT":        ("Retail", "Fashion Retail"),
    "INDHOTEL":     ("Retail", "Hotels"),

    # ── Chemicals ────────────────────────────────────────────────
    "TATACHEM":     ("Chemicals", "Chemicals"),
    "UPL":          ("Chemicals", "Agrochemicals"),

    # ── Diversified / Other ──────────────────────────────────────
    "ASIANPAINT":   ("Consumer", "Paints"),
    "PIDILITIND":   ("Consumer", "Adhesives"),
}


def get_sector(ticker: str) -> str:
    """Get sector for a ticker. Returns 'Other' if not mapped."""
    entry = SECTOR_MAP.get(ticker)
    return entry[0] if entry else "Other"


def get_industry(ticker: str) -> str:
    """Get industry sub-classification for a ticker."""
    entry = SECTOR_MAP.get(ticker)
    return entry[1] if entry else "Other"


def get_sector_industry(ticker: str) -> tuple:
    """Get (sector, industry) tuple for a ticker."""
    return SECTOR_MAP.get(ticker, ("Other", "Other"))
