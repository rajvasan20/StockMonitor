"""Theme registry — value chain definitions for thematic investing.

Each theme maps a secular macro trend to its full value chain of listed
Indian companies. Exposure levels indicate how directly the company
benefits from the theme:

    high   — core business directly driven by the theme
    medium — meaningful revenue segment, but not primary business
    low    — indirect beneficiary or small exposure
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Company:
    ticker: str
    name: str
    exposure: str       # "high", "medium", "low"
    notes: str = ""     # Why this company belongs here


@dataclass
class Segment:
    name: str
    description: str
    companies: List[Company] = field(default_factory=list)


@dataclass
class Theme:
    name: str
    slug: str               # short identifier (e.g. "data_center")
    description: str
    catalyst: str            # What's driving this theme NOW
    investment_horizon: str  # "1-3 years", "3-5 years", "5-10 years"
    segments: List[Segment] = field(default_factory=list)

    @property
    def all_tickers(self) -> List[str]:
        seen = set()
        result = []
        for seg in self.segments:
            for co in seg.companies:
                if co.ticker not in seen:
                    seen.add(co.ticker)
                    result.append(co.ticker)
        return result

    @property
    def high_exposure_tickers(self) -> List[str]:
        seen = set()
        result = []
        for seg in self.segments:
            for co in seg.companies:
                if co.exposure == "high" and co.ticker not in seen:
                    seen.add(co.ticker)
                    result.append(co.ticker)
        return result

    def get_ticker_info(self, ticker: str) -> Optional[Dict]:
        """Get theme-specific info for a ticker."""
        for seg in self.segments:
            for co in seg.companies:
                if co.ticker == ticker:
                    return {
                        "segment": seg.name,
                        "exposure": co.exposure,
                        "notes": co.notes,
                    }
        return None

    def tickers_by_segment(self) -> Dict[str, List[str]]:
        return {
            seg.name: [co.ticker for co in seg.companies]
            for seg in self.segments
        }


# ═══════════════════════════════════════════════════════════════
# THEME 1: INDIA DATA CENTER BUILDOUT
# ═══════════════════════════════════════════════════════════════

DATA_CENTER = Theme(
    name="India Data Center Buildout",
    slug="data_center",
    description=(
        "India is planning ~6 lakh crore investment in data center "
        "infrastructure, driven by AI compute demand, data localization "
        "regulations, and cloud adoption. The entire supply chain — from "
        "power equipment to cooling to cables — benefits."
    ),
    catalyst=(
        "Government policy push (Digital India, data localization), "
        "hyperscaler expansion (AWS, Azure, GCP building India regions), "
        "AI/ML compute demand explosion, 5G rollout driving edge DCs"
    ),
    investment_horizon="3-5 years",
    segments=[
        Segment(
            name="Electrical Equipment & Power Distribution",
            description=(
                "Data centers are massive power consumers (10-100+ MW each). "
                "Transformers, switchgear, bus ducts, and power distribution "
                "units are the backbone. This segment gets orders first."
            ),
            companies=[
                Company("ABB", "ABB India",
                        "high", "Switchgear, transformers, UPS, automation — full DC power stack"),
                Company("SIEMENS", "Siemens",
                        "high", "Transformers, switchgear, power distribution, building automation"),
                Company("CGPOWER", "CG Power & Industrial Solutions",
                        "high", "Transformers, switchgear, motors — strong order book growth"),
                Company("CUMMINSIND", "Cummins India",
                        "high", "DG sets — every DC needs backup power, Cummins is #1 in India"),
                Company("KIRLOSENG", "Kirloskar Oil Engines",
                        "medium", "DG sets, backup power — #2 after Cummins"),
                Company("TRITURBINE", "Triveni Turbine",
                        "low", "Small turbines for captive power — niche DC play"),
            ],
        ),
        Segment(
            name="Cables & Wiring",
            description=(
                "Power cables (HT/LT), control cables, and structured cabling "
                "for every data center. Multi-year capex cycle as DCs scale."
            ),
            companies=[
                Company("POLYCAB", "Polycab India",
                        "high", "India's largest cable manufacturer — power + data cables"),
                Company("KEI", "KEI Industries",
                        "high", "HT/LT power cables, strong institutional presence"),
                Company("HAVELLS", "Havells India",
                        "medium", "Cables + switchgear, broader consumer play dilutes exposure"),
                Company("FINCABLES", "Finolex Cables",
                        "medium", "Communication cables + power cables"),
                Company("RRKABEL", "RR Kabel",
                        "medium", "Wires and cables, growing institutional segment"),
            ],
        ),
        Segment(
            name="Fiber Optic & Networking",
            description=(
                "Interconnect between data centers and to the internet backbone. "
                "Fiber optic cables, optical networking equipment, and backhaul."
            ),
            companies=[
                Company("STLTECH", "Sterlite Technologies",
                        "high", "India's leading fiber optic cable maker — direct DC interconnect"),
                Company("HFCL", "HFCL",
                        "high", "Fiber optic cables + telecom equipment + defense fiber"),
                Company("TEJASNET", "Tejas Networks",
                        "high", "Optical networking equipment — Tata group, 5G + DC switching"),
                Company("RAILTEL", "RailTel Corporation",
                        "medium", "Fiber backbone across India, DC co-location services"),
            ],
        ),
        Segment(
            name="Cooling & HVAC",
            description=(
                "DCs generate enormous heat. Precision cooling, chillers, and "
                "HVAC systems are 30-40% of DC capex and ongoing opex."
            ),
            companies=[
                Company("BLUESTARCO", "Blue Star",
                        "high", "Precision cooling for DCs, strong institutional HVAC"),
                Company("VOLTAS", "Voltas",
                        "medium", "HVAC, commercial cooling — broader consumer mix"),
                Company("THERMAX", "Thermax",
                        "medium", "Industrial heating/cooling, boilers, chillers"),
            ],
        ),
        Segment(
            name="Energy Storage & Backup",
            description=(
                "UPS battery banks, BESS installations for power continuity. "
                "Every DC needs minutes-to-hours of battery backup."
            ),
            companies=[
                Company("ARE&M", "Amara Raja Energy & Mobility",
                        "medium", "Lead-acid + Li-ion batteries, UPS systems"),
                Company("EXIDEIND", "Exide Industries",
                        "medium", "Lead-acid batteries, expanding into Li-ion via subsidiary"),
            ],
        ),
        Segment(
            name="Construction & EPC",
            description=(
                "Data center construction is specialized EPC — raised floors, "
                "fire suppression, seismic design, Tier III/IV certification."
            ),
            companies=[
                Company("LT", "Larsen & Toubro",
                        "medium", "India's largest EPC — DC construction is a segment"),
                Company("NCC", "NCC Limited",
                        "low", "General construction — some DC/IT park exposure"),
                Company("KEC", "KEC International",
                        "low", "Power T&D, cables — RPG group, some DC infra exposure"),
            ],
        ),
        Segment(
            name="Operators & Platforms (Listed Exposure)",
            description=(
                "Companies operating or building data centers. Most pure-play "
                "DC operators in India are unlisted; listed exposure is via "
                "conglomerate parents."
            ),
            companies=[
                Company("BHARTIARTL", "Bharti Airtel",
                        "medium", "Nxtra subsidiary — one of India's largest DC operators"),
                Company("RELIANCE", "Reliance Industries",
                        "low", "Jio data centers — massive but tiny % of Reliance revenue"),
                Company("ADANIENT", "Adani Enterprises",
                        "low", "AdaniConneX JV with EdgeConneX — early stage"),
            ],
        ),
        Segment(
            name="Power Utilities (DC Power Supply)",
            description=(
                "DCs need reliable, large-scale power supply. Utilities serving "
                "DC clusters and renewable energy for green DC mandates."
            ),
            companies=[
                Company("TATAPOWER", "Tata Power",
                        "medium", "Renewable + distribution — powering DC clusters"),
                Company("NTPC", "NTPC",
                        "low", "Largest power generator — broad beneficiary"),
                Company("POWERGRID", "Power Grid Corporation",
                        "low", "Transmission infra — indirect beneficiary"),
            ],
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════
# THEME 2: DEFENSE INDIGENIZATION (ATMANIRBHAR BHARAT)
# ═══════════════════════════════════════════════════════════════

DEFENSE = Theme(
    name="India Defense Indigenization",
    slug="defense",
    description=(
        "India is the world's largest arms importer transitioning to self-reliance. "
        "Defense budget at ~6 lakh crore, with 75% domestic procurement mandate. "
        "Positive indigenization lists banning 500+ items from import."
    ),
    catalyst=(
        "Rising defense budget (6%+ annual growth), positive indigenization lists, "
        "geopolitical tensions (China/Pakistan borders), defense export push, "
        "government mandate for 75% domestic procurement"
    ),
    investment_horizon="5-10 years",
    segments=[
        Segment(
            name="Aerospace & Aviation",
            description="Fighter jets, helicopters, UAVs, engines, avionics.",
            companies=[
                Company("HAL", "Hindustan Aeronautics",
                        "high", "India's sole military aircraft maker — Tejas, LCH, ALH"),
                Company("BEL", "Bharat Electronics",
                        "high", "Avionics, radar, electronic warfare, communication systems"),
            ],
        ),
        Segment(
            name="Missiles & Ammunition",
            description="Guided missiles, torpedoes, explosives, detonators.",
            companies=[
                Company("BDL", "Bharat Dynamics",
                        "high", "Missiles (Akash, MRSAM), torpedoes — sole manufacturer"),
                Company("SOLARINDS", "Solar Industries India",
                        "high", "Explosives, defense ammunition, Pinaka rockets — export growth"),
            ],
        ),
        Segment(
            name="Naval & Shipbuilding",
            description="Warships, submarines, aircraft carriers, patrol vessels.",
            companies=[
                Company("MAZDOCK", "Mazagon Dock Shipbuilders",
                        "high", "Submarines (Scorpene), destroyers, frigates"),
                Company("GRSE", "Garden Reach Shipbuilders",
                        "high", "Frigates, corvettes, patrol vessels, landing craft"),
                Company("COCHINSHIP", "Cochin Shipyard",
                        "high", "Aircraft carrier, submarine maintenance, ship repair"),
            ],
        ),
        Segment(
            name="Land Systems & Heavy Engineering",
            description="Artillery, armored vehicles, defense platforms.",
            companies=[
                Company("BEML", "BEML",
                        "medium", "Military vehicles, earth movers, rail coaches"),
                Company("BHARATFORG", "Bharat Forge",
                        "high", "Artillery (ATAGS), defense components, aero engines — export push"),
                Company("LT", "Larsen & Toubro",
                        "medium", "Defense platforms, submarines, missiles — growing defense order book"),
            ],
        ),
        Segment(
            name="Defense Electronics & Communications",
            description="Radar, EW systems, simulators, optronics, RF components.",
            companies=[
                Company("DATAPATTNS", "Data Patterns India",
                        "high", "Electronic systems, radar sub-systems, defense avionics"),
                Company("ASTRAMICRO", "Astra Microwave Products",
                        "high", "RF and microwave components for radar and EW systems"),
                Company("PARAS", "Paras Defence and Space Technologies",
                        "high", "Defense optics, heavy engineering, electromagnetic solutions"),
                Company("ZENTEC", "Zen Technologies",
                        "high", "Combat training simulators, anti-drone systems"),
            ],
        ),
        Segment(
            name="Precision Components & Special Materials",
            description="High-precision parts for missiles, satellites, nuclear; superalloys.",
            companies=[
                Company("MTARTECH", "MTAR Technologies",
                        "high", "Precision components — missiles, space, nuclear"),
                Company("MIDHANI", "Mishra Dhatu Nigam",
                        "high", "Superalloys, titanium alloys for defense and space"),
            ],
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════
# THEME 3: ELECTRIC VEHICLE ECOSYSTEM
# ═══════════════════════════════════════════════════════════════

EV = Theme(
    name="India Electric Vehicle Ecosystem",
    slug="ev",
    description=(
        "India targeting 30% EV penetration by 2030. FAME subsidies, "
        "battery gigafactories, charging infra buildout. The entire auto "
        "value chain is pivoting — OEMs, battery, components, charging."
    ),
    catalyst=(
        "Government FAME III subsidies, PLI for battery manufacturing, "
        "rising fuel prices, tightening emission norms (BS-VII), "
        "OEM commitments to EV portfolios, falling battery costs"
    ),
    investment_horizon="3-5 years",
    segments=[
        Segment(
            name="OEMs (Vehicle Manufacturers)",
            description="Companies making electric 2W, 3W, 4W, buses.",
            companies=[
                Company("TATAMOTORS", "Tata Motors",
                        "high", "Market leader in EV 4W (Nexon, Tiago, Punch EV) — 60%+ share"),
                Company("M&M", "Mahindra & Mahindra",
                        "high", "Born Electric platform, XUV400, electric SUV lineup"),
                Company("BAJAJ-AUTO", "Bajaj Auto",
                        "medium", "Chetak EV scooter — moderate EV commitment"),
                Company("TVSMOTOR", "TVS Motor Company",
                        "medium", "iQube electric scooter — growing EV share"),
                Company("HEROMOTOCO", "Hero MotoCorp",
                        "low", "Vida V1 — late entrant, EV is small % of revenue"),
                Company("MARUTI", "Maruti Suzuki",
                        "low", "eVX announced — late to EV, but massive distribution"),
            ],
        ),
        Segment(
            name="Battery & Energy Storage",
            description="Li-ion cells, battery packs, BMS, raw materials.",
            companies=[
                Company("ARE&M", "Amara Raja Energy & Mobility",
                        "high", "Li-ion gigafactory in Telangana, battery packs for EVs"),
                Company("EXIDEIND", "Exide Industries",
                        "high", "EESL subsidiary for Li-ion — cell-to-pack manufacturing"),
                Company("TATACHEM", "Tata Chemicals",
                        "medium", "Lithium-ion cell materials, battery chemicals"),
            ],
        ),
        Segment(
            name="EV-Specific Auto Components",
            description="Motor assemblies, power electronics, BMS, wiring harnesses, EV drivetrains.",
            companies=[
                Company("SONACOMS", "Sona BLW Precision Forgings",
                        "high", "EV motor assemblies, differential gears — 30%+ revenue from EV"),
                Company("UNOMINDA", "UNO Minda",
                        "medium", "EV components — sensors, lighting, alloy wheels"),
                Company("MOTHERSON", "Samvardhana Motherson",
                        "medium", "Wiring harnesses, modules — EV content per vehicle is higher"),
                Company("BOSCHLTD", "Bosch",
                        "medium", "EV motor controllers, power electronics, ADAS"),
            ],
        ),
        Segment(
            name="Charging Infrastructure",
            description="EV charging stations, charger manufacturing, power management.",
            companies=[
                Company("TATAPOWER", "Tata Power",
                        "high", "India's largest EV charging network (5000+ stations)"),
                Company("EXICOM", "Exicom Tele-Systems",
                        "high", "EV charger manufacturing — DC fast chargers"),
            ],
        ),
        Segment(
            name="Cables & Electrical (EV Infra)",
            description="Charging cables, power cables for charging stations, grid upgrades.",
            companies=[
                Company("POLYCAB", "Polycab India",
                        "medium", "EV charging cables, power infra for charging stations"),
                Company("KEI", "KEI Industries",
                        "low", "Power cables for grid upgrades needed for EV charging load"),
            ],
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════
# THEME 4: SEMICONDUCTOR & ELECTRONICS MANUFACTURING
# ═══════════════════════════════════════════════════════════════

SEMICONDUCTOR = Theme(
    name="India Semiconductor & Electronics Manufacturing",
    slug="semiconductor",
    description=(
        "India Semiconductor Mission (~76,000 Cr), PLI for electronics, "
        "OSAT/packaging plants approved (Tata, CG, Kaynes), chip design "
        "talent (20% of world's IC designers are Indian). From fab to EMS."
    ),
    catalyst=(
        "India Semiconductor Mission, PLI schemes for electronics, "
        "global supply chain diversification (China+1), Apple/Samsung "
        "manufacturing shift to India, OSAT plant approvals (Tata, CG Power)"
    ),
    investment_horizon="5-10 years",
    segments=[
        Segment(
            name="EMS & Contract Manufacturing",
            description=(
                "Electronics Manufacturing Services — PCB assembly, box build, "
                "system integration. The picks-and-shovels of India's electronics push."
            ),
            companies=[
                Company("DIXON", "Dixon Technologies",
                        "high", "India's largest EMS — mobiles, TVs, LED, washing machines"),
                Company("KAYNES", "Kaynes Technology",
                        "high", "PCB assembly, IoT, automotive electronics — OSAT plant approved"),
                Company("SYRMA", "Syrma SGS Technology",
                        "high", "PCBA, RFID, IoT — defense + industrial electronics"),
                Company("AVALON", "Avalon Technologies",
                        "medium", "PCB fabrication, box build — US/India operations"),
            ],
        ),
        Segment(
            name="Semiconductor Design & IP",
            description="Chip design services, embedded software, VLSI — India's core strength.",
            companies=[
                Company("KPITTECH", "KPIT Technologies",
                        "high", "Automotive embedded software, SDV, semiconductor IP"),
                Company("TATAELXSI", "Tata Elxsi",
                        "high", "Chip design services, multimedia, automotive ASIC design"),
                Company("SASKEN", "Sasken Technologies",
                        "medium", "Semiconductor design, product engineering services"),
            ],
        ),
        Segment(
            name="Electrical Components (Semiconductor Adjacent)",
            description=(
                "Companies positioning for fab/OSAT ecosystem — packaging, "
                "power electronics, precision components."
            ),
            companies=[
                Company("CGPOWER", "CG Power & Industrial Solutions",
                        "high", "OSAT plant approved — entering semiconductor packaging"),
                Company("ABB", "ABB India",
                        "medium", "Power electronics, automation for fab operations"),
                Company("SIEMENS", "Siemens",
                        "medium", "Factory automation, power systems for fabs"),
            ],
        ),
        Segment(
            name="Materials & Gases",
            description="Specialty chemicals, industrial gases, ultra-pure materials for fabs.",
            companies=[
                Company("LINDEINDIA", "Linde India",
                        "high", "Industrial gases — critical for semiconductor fabs"),
                Company("CLEAN", "Clean Science and Technology",
                        "low", "Specialty chemicals — potential fab material supplier"),
            ],
        ),
        Segment(
            name="Precision Engineering",
            description="High-precision components for semiconductor equipment and testing.",
            companies=[
                Company("MTARTECH", "MTAR Technologies",
                        "medium", "Precision engineering — potential semi equipment supplier"),
            ],
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════
# THEME REGISTRY
# ═══════════════════════════════════════════════════════════════

THEMES: Dict[str, Theme] = {
    "data_center": DATA_CENTER,
    "defense": DEFENSE,
    "ev": EV,
    "semiconductor": SEMICONDUCTOR,
}


def get_theme(slug: str) -> Optional[Theme]:
    return THEMES.get(slug)


def get_all_themes() -> Dict[str, Theme]:
    return THEMES


def get_all_thematic_tickers() -> List[str]:
    """All unique tickers across all themes."""
    seen = set()
    result = []
    for theme in THEMES.values():
        for t in theme.all_tickers:
            if t not in seen:
                seen.add(t)
                result.append(t)
    return result


def find_themes_for_ticker(ticker: str) -> List[Dict]:
    """Find all themes a ticker belongs to, with segment and exposure info."""
    results = []
    for theme in THEMES.values():
        info = theme.get_ticker_info(ticker)
        if info:
            results.append({
                "theme": theme.name,
                "theme_slug": theme.slug,
                **info,
            })
    return results
