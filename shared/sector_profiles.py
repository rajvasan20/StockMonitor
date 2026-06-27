"""Sector-specific valuation profiles for Indian equities.

Maps Screener.in sector names to valuation parameters:
    - Discount rate (WACC proxy)
    - Fair EV/EBITDA multiple range
    - Method weights for composite IV
    - PEG P/E floor and ceiling
    - Historical P/E norms (typical trading range)
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class SectorProfile:
    """Valuation parameters for a sector."""
    name: str
    discount_rate: float              # WACC proxy
    ev_ebitda_range: Tuple[int, int]  # (low, high) fair multiple
    pe_range: Tuple[int, int]         # typical P/E trading range
    peg_pe_floor: int                 # minimum fair P/E for PEG method
    peg_pe_ceiling: int               # maximum fair P/E for PEG method
    method_weights: Dict[str, float] = field(default_factory=dict)
    # Weights: Graham Number, DCF, PEG Ratio, EV/EBITDA, EPV


# ── Sector Definitions ───────────────────────────────────────────────────────

PROFILES = {
    "Information Technology": SectorProfile(
        name="Information Technology",
        discount_rate=0.10,           # Low-risk, capital-light, stable cash flows
        ev_ebitda_range=(14, 22),     # IT services trade at premium multiples
        pe_range=(18, 35),
        peg_pe_floor=15,             # High-ROE businesses deserve higher floor
        peg_pe_ceiling=40,
        method_weights={
            "Graham Number": 0.05,    # Penalizes asset-light high-ROE businesses
            "DCF": 0.35,              # Best method for stable cash generators
            "PEG Ratio": 0.20,
            "EV/EBITDA": 0.30,
            "Earnings Power Value": 0.10,  # Zero-growth floor, useful but low weight
        },
    ),

    "Energy": SectorProfile(
        name="Energy",
        discount_rate=0.13,           # Capital-intensive, cyclical
        ev_ebitda_range=(6, 10),
        pe_range=(8, 18),
        peg_pe_floor=8,
        peg_pe_ceiling=20,
        method_weights={
            "Graham Number": 0.15,
            "DCF": 0.30,
            "PEG Ratio": 0.10,       # Growth volatile in commodity businesses
            "EV/EBITDA": 0.35,        # Primary metric for O&G / energy
            "Earnings Power Value": 0.10,
        },
    ),

    "Financial Services": SectorProfile(
        name="Financial Services",
        discount_rate=0.12,
        ev_ebitda_range=(8, 14),      # Less relevant for banks (use P/B instead)
        pe_range=(10, 22),
        peg_pe_floor=10,
        peg_pe_ceiling=25,
        method_weights={
            "Graham Number": 0.25,    # Book value is meaningful for banks
            "DCF": 0.15,              # Difficult for banks (what is FCF?)
            "PEG Ratio": 0.20,
            "EV/EBITDA": 0.15,        # Less meaningful for financials
            "Earnings Power Value": 0.25,  # Normalized earnings is key for banks
        },
    ),

    "Fast Moving Consumer Goods": SectorProfile(
        name="Fast Moving Consumer Goods",
        discount_rate=0.10,           # Defensive, stable
        ev_ebitda_range=(20, 35),     # FMCG commands premium multiples in India
        pe_range=(30, 60),
        peg_pe_floor=20,
        peg_pe_ceiling=50,
        method_weights={
            "Graham Number": 0.05,    # Asset-light, high-ROE — Graham penalizes
            "DCF": 0.35,
            "PEG Ratio": 0.25,        # Steady growers — PEG is meaningful
            "EV/EBITDA": 0.25,
            "Earnings Power Value": 0.10,
        },
    ),

    "Healthcare": SectorProfile(
        name="Healthcare",
        discount_rate=0.11,
        ev_ebitda_range=(12, 22),
        pe_range=(15, 35),
        peg_pe_floor=12,
        peg_pe_ceiling=35,
        method_weights={
            "Graham Number": 0.10,
            "DCF": 0.30,
            "PEG Ratio": 0.25,
            "EV/EBITDA": 0.25,
            "Earnings Power Value": 0.10,
        },
    ),

    "Automobile and Auto Components": SectorProfile(
        name="Automobile and Auto Components",
        discount_rate=0.12,
        ev_ebitda_range=(8, 16),
        pe_range=(12, 30),
        peg_pe_floor=10,
        peg_pe_ceiling=30,
        method_weights={
            "Graham Number": 0.15,
            "DCF": 0.25,
            "PEG Ratio": 0.20,
            "EV/EBITDA": 0.25,
            "Earnings Power Value": 0.15,
        },
    ),

    "Capital Goods": SectorProfile(
        name="Capital Goods",
        discount_rate=0.12,
        ev_ebitda_range=(12, 22),
        pe_range=(20, 45),
        peg_pe_floor=12,
        peg_pe_ceiling=40,
        method_weights={
            "Graham Number": 0.10,
            "DCF": 0.30,
            "PEG Ratio": 0.25,
            "EV/EBITDA": 0.25,
            "Earnings Power Value": 0.10,
        },
    ),

    "Consumer Durables": SectorProfile(
        name="Consumer Durables",
        discount_rate=0.11,
        ev_ebitda_range=(15, 28),
        pe_range=(25, 50),
        peg_pe_floor=15,
        peg_pe_ceiling=40,
        method_weights={
            "Graham Number": 0.05,
            "DCF": 0.30,
            "PEG Ratio": 0.25,
            "EV/EBITDA": 0.30,
            "Earnings Power Value": 0.10,
        },
    ),

    "Metals & Mining": SectorProfile(
        name="Metals & Mining",
        discount_rate=0.14,           # Highly cyclical
        ev_ebitda_range=(4, 8),
        pe_range=(5, 15),
        peg_pe_floor=6,
        peg_pe_ceiling=15,
        method_weights={
            "Graham Number": 0.20,    # Asset-heavy — book value matters
            "DCF": 0.15,              # Cash flows too volatile for DCF
            "PEG Ratio": 0.10,        # Growth is cyclical, not structural
            "EV/EBITDA": 0.35,        # Primary valuation metric for metals
            "Earnings Power Value": 0.20,  # Normalized earnings useful for cycles
        },
    ),

    "Construction Materials": SectorProfile(
        name="Construction Materials",
        discount_rate=0.12,
        ev_ebitda_range=(10, 18),
        pe_range=(15, 35),
        peg_pe_floor=10,
        peg_pe_ceiling=30,
        method_weights={
            "Graham Number": 0.15,
            "DCF": 0.25,
            "PEG Ratio": 0.15,
            "EV/EBITDA": 0.30,
            "Earnings Power Value": 0.15,
        },
    ),

    "Telecommunication": SectorProfile(
        name="Telecommunication",
        discount_rate=0.12,
        ev_ebitda_range=(7, 12),
        pe_range=(15, 35),
        peg_pe_floor=10,
        peg_pe_ceiling=30,
        method_weights={
            "Graham Number": 0.10,
            "DCF": 0.30,
            "PEG Ratio": 0.15,
            "EV/EBITDA": 0.35,        # EV/EBITDA is key for telcos
            "Earnings Power Value": 0.10,
        },
    ),

    "Chemicals": SectorProfile(
        name="Chemicals",
        discount_rate=0.12,
        ev_ebitda_range=(10, 20),
        pe_range=(15, 35),
        peg_pe_floor=10,
        peg_pe_ceiling=30,
        method_weights={
            "Graham Number": 0.15,
            "DCF": 0.25,
            "PEG Ratio": 0.20,
            "EV/EBITDA": 0.25,
            "Earnings Power Value": 0.15,
        },
    ),

    "Realty": SectorProfile(
        name="Realty",
        discount_rate=0.14,           # High risk, cyclical
        ev_ebitda_range=(6, 12),
        pe_range=(8, 20),
        peg_pe_floor=8,
        peg_pe_ceiling=20,
        method_weights={
            "Graham Number": 0.25,    # NAV/book value very relevant
            "DCF": 0.20,
            "PEG Ratio": 0.10,
            "EV/EBITDA": 0.25,
            "Earnings Power Value": 0.20,
        },
    ),

    "Power": SectorProfile(
        name="Power",
        discount_rate=0.11,           # Regulated, stable but low growth
        ev_ebitda_range=(7, 12),
        pe_range=(10, 20),
        peg_pe_floor=8,
        peg_pe_ceiling=20,
        method_weights={
            "Graham Number": 0.15,
            "DCF": 0.30,
            "PEG Ratio": 0.10,
            "EV/EBITDA": 0.30,
            "Earnings Power Value": 0.15,
        },
    ),

    "Services": SectorProfile(
        name="Services",
        discount_rate=0.11,
        ev_ebitda_range=(10, 20),
        pe_range=(15, 30),
        peg_pe_floor=12,
        peg_pe_ceiling=30,
        method_weights={
            "Graham Number": 0.10,
            "DCF": 0.30,
            "PEG Ratio": 0.20,
            "EV/EBITDA": 0.25,
            "Earnings Power Value": 0.15,
        },
    ),
}


# ── Default profile for unknown sectors ───────────────────────────────────────

DEFAULT_PROFILE = SectorProfile(
    name="Other",
    discount_rate=0.12,
    ev_ebitda_range=(8, 14),
    pe_range=(12, 25),
    peg_pe_floor=10,
    peg_pe_ceiling=30,
    method_weights={
        "Graham Number": 0.15,
        "DCF": 0.25,
        "PEG Ratio": 0.20,
        "EV/EBITDA": 0.25,
        "Earnings Power Value": 0.15,
    },
)


# ── Bank-specific method weights ─────────────────────────────────────────────
# Used when sector == "Financial Services" — replaces the standard 5 methods

BANK_METHOD_WEIGHTS = {
    "Gordon Growth P/B": 0.35,     # Primary: P/B from ROE vs CoE
    "Justified P/E": 0.20,         # P/E derived from P/B model
    "Dividend Discount": 0.15,     # Banks are reliable dividend payers
    "Residual Income": 0.20,       # BV + PV of excess returns
    "P/B Mean Reversion": 0.10,    # Historical P/B anchor
}


def get_sector_profile(sector_name):
    """Look up sector profile. Falls back to DEFAULT_PROFILE."""
    if sector_name and sector_name in PROFILES:
        return PROFILES[sector_name]
    return DEFAULT_PROFILE


def get_quality_adjusted_peg_floor(profile, roe):
    """Adjust PEG P/E floor upward for high-quality (high-ROE) businesses.

    Rationale: A company with 50% ROE growing at 7% deserves a higher P/E
    than a company with 10% ROE growing at 7%. High ROE means the company
    can compound value even at modest growth rates.
    """
    base_floor = profile.peg_pe_floor
    if roe is None:
        return base_floor

    # ROE as decimal (0-1 range)
    roe_dec = roe / 100 if roe > 1 else roe

    if roe_dec >= 0.30:
        return max(base_floor, int(base_floor * 1.8))
    elif roe_dec >= 0.20:
        return max(base_floor, int(base_floor * 1.4))
    elif roe_dec >= 0.15:
        return max(base_floor, int(base_floor * 1.2))
    return base_floor
