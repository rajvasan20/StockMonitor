"""Central configuration for Stock Monitor.

Project structure:
    Stock Monitor/
    ├── shared/              # Shared infra (scraper, parser, utils)
    ├── universe_monitor/    # Module 1: Scan all NSE equities
    ├── red_flag/            # Module 2: Red flag detection per company
    ├── investment_thesis/   # Module 3: 5-slider investment report
    ├── themes/              # Module 4: Thematic value chain screening
    ├── technicals/          # Module 5: Technical analysis (RSI, MACD, CPR)
    ├── short_term/          # Module 6: Short-term convergence screener
    ├── data/                # Runtime data (tickers, caches, annual reports)
    ├── output/              # Generated output (summaries, analyses)
    ├── reports/             # Per-ticker valuation markdown reports
    └── logs/
"""

import os

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Module-specific data paths
ANNUAL_REPORTS_DIR = os.path.join(DATA_DIR, "annual_reports")
TICKER_EXCELS_DIR = os.path.join(DATA_DIR, "ticker_excels")
SHAREHOLDING_DIR = os.path.join(DATA_DIR, "shareholding")
NOTES_EXCEL_DIR = os.path.join(OUTPUT_DIR, "notes_excel")
ANALYSES_DIR = os.path.join(OUTPUT_DIR, "analyses")

# Management Integrity
INTEGRITY_DIR = os.path.join(DATA_DIR, "integrity")
INTEGRITY_REPORTS_DIR = os.path.join(OUTPUT_DIR, "integrity_reports")

# PPT Reports
PPTX_DIR = os.path.join(OUTPUT_DIR, "pptx_decks")
QUALITY_DATA_PATH = os.path.join(OUTPUT_DIR, "quality_reports", "_quality_data.json")

# ── Screener.in ───────────────────────────────────────────────────────────────
SCREENER_BASE_URL = "https://www.screener.in/company/{ticker}/{variant}/"
REQUEST_DELAY_SECONDS = 3
REQUEST_DELAY_JITTER = 2
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
REQUEST_TIMEOUT = 30

# ── NSE Ticker Source ─────────────────────────────────────────────────────────
NSE_EQUITY_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

# ── Valuation Parameters ─────────────────────────────────────────────────────
RISK_FREE_RATE = 0.07        # Indian 10-year G-Sec yield
MARKET_RETURN = 0.12         # Long-term Nifty CAGR
EQUITY_RISK_PREMIUM = MARKET_RETURN - RISK_FREE_RATE
TERMINAL_GROWTH_RATE = 0.04  # Conservative GDP growth
DEFAULT_DISCOUNT_RATE = 0.12 # WACC proxy
MARGIN_OF_SAFETY = 0.30      # 30% below intrinsic = bargain

# ── Bargain Thresholds ───────────────────────────────────────────────────────
BARGAIN_MIN_METHODS_AGREE = 3  # 3 of 5 methods must agree (was 4 of 10)
BARGAIN_UPSIDE_THRESHOLD = 0.30
BARGAIN_MAX_DE_RATIO = 2.0

# ── Email ─────────────────────────────────────────────────────────────────────
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = os.environ.get("STOCK_MONITOR_EMAIL_FROM", "")
EMAIL_APP_PASSWORD = os.environ.get("STOCK_MONITOR_EMAIL_PWD", "")
EMAIL_TO = "vrvk1986@gmail.com"

# ── Cycle ─────────────────────────────────────────────────────────────────────
FULL_CYCLE_PAUSE_HOURS = 24  # Pause between full cycles
TICKER_CACHE_MAX_AGE_DAYS = 7

# ── Thematic Screening ──────────────────────────────────────────────────────
THEMATIC_PEG_MAX = 1.5
THEMATIC_ROCE_MIN = 12.0          # %
THEMATIC_REVENUE_CAGR_MIN = 0.15  # 15% 3-year CAGR
THEMATIC_DE_MAX = 1.5             # higher tolerance for capex-heavy
THEMATIC_CURRENT_RATIO_MIN = 1.2
THEMATIC_CFO_PROFIT_MIN = 0.60

# ── Technical Analysis ──────────────────────────────────────────────────────
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
VOLUME_SMA_PERIOD = 20
VOLUME_SPIKE_THRESHOLD = 1.5
HIGH_DELIVERY_PCT = 70.0

# ── Short-Term Convergence ──────────────────────────────────────────────────
CONVERGENCE_TECH_MIN_SCORE = 2     # minimum technical score for convergence
CONVERGENCE_FUND_MIN_TRIGGERS = 1  # minimum fundamental triggers
