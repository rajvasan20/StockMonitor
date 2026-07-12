"""
NIFTY 50 Annual Report Downloader — Multi-Source
==================================================
Downloads annual reports for all NIFTY 50 companies from multiple sources:
  1. BSE Official API          (primary)
  2. NSE Official Filing API   (fallback #1)
  3. Screener.in               (fallback #2)
  4. Company IR pages          (fallback #3)

Usage:
    python run.py redflag-download                          # All NIFTY 50
    python run.py redflag-download --companies TCS,INFY     # Specific
    python run.py redflag-download --from-year 2019         # Custom range
"""

import os
import re
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from config import ANNUAL_REPORTS_DIR

# ─────────────────────────────────────────────────────────────────────────────
# Master Registry — NIFTY 50 + additional tickers
# ─────────────────────────────────────────────────────────────────────────────
EXTRA_TICKERS = {
    "NEWGEN":     {"bse": 540900, "nse": "NEWGEN",     "screener": "newgen-software-technologies",    "ir": "https://newgensoft.com/company/investor-relations/complete-annual-report-including-balance-sheet-profit-and-loss-account/"},
    "NCC":        {"bse": 500294, "nse": "NCC",        "screener": "ncc",                             "ir": "https://ncclimited.com/annual-reports.html"},
    "ABB":        {"bse": 500002, "nse": "ABB",        "screener": "abb",                             "ir": "https://new.abb.com/indian-subcontinent/investors/financial-results-and-presentations/quarterly-results-and-annual-reports-2025"},
    "CGPOWER":    {"bse": 500093, "nse": "CGPOWER",    "screener": "cg-power-and-industrial-solutions", "ir": "https://www.cgglobal.com/financials"},
    "CUMMINSIND": {"bse": 500480, "nse": "CUMMINSIND", "screener": "cummins-india",                   "ir": "https://www.cummins.com/en-na/en/in/investors/india-annual-reports"},
    "SIEMENS":    {"bse": 500550, "nse": "SIEMENS",    "screener": "siemens",                         "ir": "https://www.siemens.com/in/en/company/investor-relations/annual-reports.html"},
    "KIRLOSENG":  {"bse": 533293, "nse": "KIRLOSENG",  "screener": "kirloskar-oil-engines",           "ir": "https://www.kirloskaroilengines.com/investors/annual-reports"},
    "TRITURBINE": {"bse": 533655, "nse": "TRITURBINE", "screener": "triveni-turbine",                 "ir": "https://www.triveniturbines.com/investors/financials/annual-reports/"},
    "BERGEPAINT": {"bse": 509480, "nse": "BERGEPAINT", "screener": "berger-paints",                   "ir": "https://www.bergerpaints.com/investor-relation#annual-report"},
    "KANSAINER":  {"bse": 500165, "nse": "KANSAINER",  "screener": "kansai-nerolac-paints",           "ir": "https://www.nerolac.com/about-us/investor-centre.html"},
    "MAXHEALTH":  {"bse": 543220, "nse": "MAXHEALTH",  "screener": "max-healthcare-institute",        "ir": "https://www.maxhealthcare.in/investor-relations/annual-report"},
    "FORTIS":     {"bse": 532843, "nse": "FORTIS",     "screener": "fortis-healthcare",               "ir": "https://www.fortishealthcare.com/investor-relation"},
    "NATCOPHARM": {"bse": 524816, "nse": "NATCOPHARM", "screener": "natco-pharma",                    "ir": "https://www.natcopharma.co.in/investors/annual-reports/"},
    "AHCL":       {"bse": 544497, "nse": "AHCL",       "screener": "anlon-healthcare",                "ir": ""},
    # ── Quality Universe (43 companies) ──────────────────────────────────────
    "DRCSYSTEMS": {"bse": 543268, "nse": "DRCSYSTEMS", "screener": "drc-systems-india",               "ir": ""},
    "ECOSMOBLTY": {"bse": 544239, "nse": "ECOSMOBLTY", "screener": "ecos-india-mobility-and-hospitality", "ir": ""},
    "ACE":        {"bse": 532762, "nse": "ACE",        "screener": "action-construction-equipment",      "ir": ""},
    "AGIIL":      {"bse": 539042, "nse": "AGIIL",      "screener": "agi-infra",                       "ir": ""},
    "ALKYLAMINE": {"bse": 506767, "nse": "ALKYLAMINE", "screener": "alkyl-amines-chemicals",          "ir": ""},
    "ALLDIGI":    {"bse": 532633, "nse": "ALLDIGI",    "screener": "alldigi-tech",                    "ir": ""},
    "BLS":        {"bse": 540073, "nse": "BLS",        "screener": "bls-international-services",      "ir": ""},
    "CAMS":       {"bse": 543232, "nse": "CAMS",       "screener": "computer-age-management-services","ir": ""},
    "CDSL":       {"bse": 532461, "nse": "CDSL",       "screener": "central-depository-services",     "ir": ""},
    "COFORGE":    {"bse": 532541, "nse": "COFORGE",    "screener": "coforge",                         "ir": ""},
    "CONTROLPR":  {"bse": 522295, "nse": "CONTROLPR",  "screener": "control-print",                   "ir": ""},
    "CRISIL":     {"bse": 500092, "nse": "CRISIL",     "screener": "crisil",                          "ir": ""},
    "ECLERX":     {"bse": 532927, "nse": "ECLERX",     "screener": "eclerx-services",                 "ir": ""},
    "GPIL":       {"bse": 532734, "nse": "GPIL",       "screener": "godawari-power-and-ispat",        "ir": ""},
    "GRAUWEIL":   {"bse": 505710, "nse": "GRAUWEIL",   "screener": "grauer-and-weil",                 "ir": ""},
    "GRINDWELL":  {"bse": 506076, "nse": "GRINDWELL",  "screener": "grindwell-norton",                "ir": ""},
    "GRWRHITECH": {"bse": 500655, "nse": "GRWRHITECH", "screener": "garware-hi-tech-films",           "ir": ""},
    "IEX":        {"bse": 540750, "nse": "IEX",        "screener": "indian-energy-exchange",          "ir": ""},
    "INDIAMART":  {"bse": 542726, "nse": "INDIAMART",  "screener": "indiamart-intermesh",             "ir": ""},
    "INDUSTOWER": {"bse": 534816, "nse": "INDUSTOWER", "screener": "indus-towers",                    "ir": ""},
    "INOXINDIA":  {"bse": 544046, "nse": "INOXINDIA",  "screener": "inox-india",                      "ir": ""},
    "JBCHEPHARM": {"bse": 506943, "nse": "JBCHEPHARM", "screener": "j-b-chemicals-and-pharmaceuticals","ir": ""},
    "JLHL":       {"bse": 543980, "nse": "JLHL",       "screener": "jupiter-life-line-hospitals",     "ir": ""},
    "JYOTHYLAB":  {"bse": 532926, "nse": "JYOTHYLAB",  "screener": "jyothy-labs",                     "ir": ""},
    "KFINTECH":   {"bse": 543720, "nse": "KFINTECH",   "screener": "kfin-technologies",               "ir": ""},
    "KPITTECH":   {"bse": 542651, "nse": "KPITTECH",   "screener": "kpit-technologies",               "ir": ""},
    "LALPATHLAB": {"bse": 539524, "nse": "LALPATHLAB", "screener": "dr-lal-pathlabs",                 "ir": ""},
    "LTM":        {"bse": 540005, "nse": "LTM",        "screener": "lt-mindtree",                     "ir": ""},
    "MCX":        {"bse": 534091, "nse": "MCX",        "screener": "multi-commodity-exchange-of-india","ir": ""},
    "MEDANTA":    {"bse": 543654, "nse": "MEDANTA",    "screener": "global-health",                   "ir": ""},
    "NATIONALUM": {"bse": 532234, "nse": "NATIONALUM", "screener": "national-aluminium-company",      "ir": ""},
    "NH":         {"bse": 539551, "nse": "NH",         "screener": "narayana-hrudayalaya",            "ir": ""},
    "PERSISTENT": {"bse": 533179, "nse": "PERSISTENT", "screener": "persistent-systems",              "ir": ""},
    "PIDILITIND": {"bse": 500331, "nse": "PIDILITIND", "screener": "pidilite-industries",             "ir": ""},
    "PIIND":      {"bse": 523642, "nse": "PIIND",      "screener": "p-i-industries",                  "ir": ""},
    "RAINBOW":    {"bse": 543524, "nse": "RAINBOW",    "screener": "rainbow-childrens-medicare",      "ir": ""},
    "SOLARINDS":  {"bse": 532725, "nse": "SOLARINDS",  "screener": "solar-industries-india",          "ir": ""},
    "SUPREMEIND": {"bse": 509930, "nse": "SUPREMEIND", "screener": "supreme-industries",              "ir": ""},
    "TATAELXSI":  {"bse": 500408, "nse": "TATAELXSI",  "screener": "tata-elxsi",                      "ir": ""},
    "TATATECH":   {"bse": 544028, "nse": "TATATECH",   "screener": "tata-technologies",               "ir": ""},
    "TRAVELFOOD": {"bse": 544443, "nse": "TRAVELFOOD", "screener": "travel-food-services",            "ir": ""},
    "VIJAYA":     {"bse": 543350, "nse": "VIJAYA",     "screener": "vijaya-diagnostic-centre",        "ir": ""},
    "ZYDUSLIFE":  {"bse": 532321, "nse": "ZYDUSLIFE",  "screener": "zydus-lifesciences",              "ir": ""},
    "KPRMILL":    {"bse": 532889, "nse": "KPRMILL",    "screener": "k-p-r-mill",                      "ir": ""},
    "STYL":       {"bse": 544533, "nse": "STYL",       "screener": "seshaasai-technologies",           "ir": ""},
    "OSWALPUMPS": {"bse": 544418, "nse": "OSWALPUMPS", "screener": "oswal-pumps",                     "ir": ""},
    "GANDHITUBE": {"bse": 513108, "nse": "GANDHITUBE", "screener": "gandhi-special-tubes",            "ir": ""},
    "MANAPPURAM": {"bse": 531213, "nse": "MANAPPURAM", "screener": "manappuram-finance",             "ir": ""},
    "SOUTHBANK": {"bse": 532218, "nse": "SOUTHBANK", "screener": "south-indian-bank",               "ir": ""},
    "MANKIND":   {"bse": 543904, "nse": "MANKIND",   "screener": "mankind-pharma",                  "ir": ""},
    # ── Steel Tubes & Pipes ──────────────────────────────────────────────────
    "RATNAMANI": {"bse": 520111, "nse": "RATNAMANI", "screener": "ratnamani-metals-and-tubes",      "ir": ""},
    "MAHSEAMLES": {"bse": 500265, "nse": "MAHSEAMLES", "screener": "maharashtra-seamless",          "ir": ""},
    "APLAPOLLO": {"bse": 533758, "nse": "APLAPOLLO", "screener": "apl-apollo-tubes",               "ir": ""},
    "JINDALSAW": {"bse": 500378, "nse": "JINDALSAW", "screener": "jindal-saw",                     "ir": ""},
    "RRKABEL":   {"bse": 543981, "nse": "RRKABEL",   "screener": "r-r-kabel",                      "ir": ""},
    "EPACK":     {"bse": 544095, "nse": "EPACK",     "screener": "epack-durable",                  "ir": ""},
    "CEMPRO":    {"bse": 509496, "nse": "CEMPRO",   "screener": "CEMPRO",                        "ir": ""},
    "BLUESTARCO": {"bse": 500067, "nse": "BLUESTARCO", "screener": "blue-star",                    "ir": "https://www.bluestarindia.com/investors/annual-report"},
    "THERMAX":   {"bse": 500411, "nse": "THERMAX",   "screener": "thermax",                      "ir": ""},
    "KEI":       {"bse": 517569, "nse": "KEI",       "screener": "kei-industries",                "ir": ""},
    "LLOYDSENGG": {"bse": 539992, "nse": "LLOYDSENGG", "screener": "lloyds-engineering-works",      "ir": ""},
    "APOLLO":     {"bse": 540879, "nse": "APOLLO",     "screener": "apollo-micro-systems",           "ir": ""},
    "AEGISLOG":   {"bse": 500003, "nse": "AEGISLOG",   "screener": "aegis-logistics",                "ir": ""},
    "AVALON":     {"bse": 543896, "nse": "AVALON",     "screener": "avalon-technologies",             "ir": ""},
    "BEL":        {"bse": 500049, "nse": "BEL",        "screener": "bharat-electronics",              "ir": "https://bel-india.in/annual-reports"},
    "HINDALCO":   {"bse": 500440, "nse": "HINDALCO",   "screener": "hindalco-industries",              "ir": ""},
    "ETERNAL":    {"bse": 543320, "nse": "ETERNAL",    "screener": "eternal",                          "ir": "https://www.eternal.com/investors"},
    "JIOFIN":     {"bse": 543940, "nse": "JIOFIN",    "screener": "jio-financial-services",            "ir": ""},
    "MARKSANS":   {"bse": 524404, "nse": "MARKSANS",  "screener": "marksans-pharma",                   "ir": ""},
    "KRN":        {"bse": 544263, "nse": "KRN",      "screener": "krn-heat-exchanger-and-refrigeration", "ir": ""},
    "AEQUS":      {"bse": 213862, "nse": "AEQUS",   "screener": "aequs",                               "ir": ""},
    "SAMMAANCAP": {"bse": 535789, "nse": "SAMMAANCAP", "screener": "sammaan-capital",                   "ir": ""},
    "PAR":        {"bse": 531399, "nse": "PAR",       "screener": "par-drugs-and-chemicals",             "ir": "https://www.pardrugs.com/pdf/notices/"},
    "AWL":        {"bse": 543458, "nse": "AWL",       "screener": "awl-agri-business",                   "ir": ""},
    "GVT&D":      {"bse": 522275, "nse": "GVT&D",    "screener": "ge-vernova-t-d-india",                 "ir": ""},
    "HOMEFIRST":  {"bse": 543259, "nse": "HOMEFIRST", "screener": "home-first-finance-company-india",    "ir": "https://www.homefirstindia.com/investor-relations"},
    "IDEA":       {"bse": 532822, "nse": "IDEA",     "screener": "vodafone-idea",                          "ir": "https://www.myvi.in/about-us/investors/annual-reports"},
    "ABBOTINDIA": {"bse": 500488, "nse": "ABBOTINDIA", "screener": "abbott-india",                         "ir": "https://www.abbott.co.in/investors/annual-reports.html"},
}

NIFTY50 = {
    "ADANIENT":   {"bse": 512599, "nse": "ADANIENT",   "screener": "adani-enterprises",               "ir": "https://www.adanienterprises.com/investors/annual-reports"},
    "ADANIPORTS": {"bse": 532921, "nse": "ADANIPORTS",  "screener": "adani-ports-and-sez",             "ir": "https://www.adaniports.com/Investors/Annual-Reports"},
    "APOLLOHOSP": {"bse": 508869, "nse": "APOLLOHOSP",  "screener": "apollo-hospitals-enterprise",     "ir": "https://www.apollohospitals.com/investors/annual-report"},
    "ASIANPAINT": {"bse": 500820, "nse": "ASIANPAINT",  "screener": "asian-paints",                    "ir": "https://www.asianpaints.com/investor-relations/annual-report.html"},
    "AXISBANK":   {"bse": 532215, "nse": "AXISBANK",    "screener": "axis-bank",                       "ir": "https://www.axisbank.com/investor-relations/annual-report"},
    "BAJAJ-AUTO": {"bse": 532977, "nse": "BAJAJ-AUTO",  "screener": "bajaj-auto",                      "ir": "https://www.bajajauto.com/investors/annual-reports"},
    "BAJFINANCE": {"bse": 500034, "nse": "BAJFINANCE",  "screener": "bajaj-finance",                   "ir": "https://www.bajajfinserv.in/bajaj-finance-annual-report"},
    "BAJAJFINSV": {"bse": 532978, "nse": "BAJAJFINSV",  "screener": "bajaj-finserv",                   "ir": "https://www.bajajfinserv.in/investors/annual-reports"},
    "BHARTIARTL": {"bse": 532454, "nse": "BHARTIARTL",  "screener": "bharti-airtel",                   "ir": "https://www.airtel.in/investors/annual-report"},
    "BPCL":       {"bse": 500547, "nse": "BPCL",        "screener": "bharat-petroleum-corporation",    "ir": "https://www.bharatpetroleum.in/investor-relations/annual-report.aspx"},
    "BRITANNIA":  {"bse": 500825, "nse": "BRITANNIA",   "screener": "britannia-industries",            "ir": "https://www.britanniaindustries.com/investors/annual-report"},
    "CIPLA":      {"bse": 500087, "nse": "CIPLA",       "screener": "cipla",                           "ir": "https://www.cipla.com/investors/annual-reports"},
    "COALINDIA":  {"bse": 533278, "nse": "COALINDIA",   "screener": "coal-india",                      "ir": "https://www.coalindia.in/en-us/investor/annual-reports.aspx"},
    "DIVISLAB":   {"bse": 532488, "nse": "DIVISLAB",    "screener": "divis-laboratories",              "ir": "https://www.divislab.com/investors/annual-reports"},
    "DRREDDY":    {"bse": 500124, "nse": "DRREDDY",     "screener": "dr-reddys-laboratories",          "ir": "https://www.drreddys.com/investors/annual-reports"},
    "EICHERMOT":  {"bse": 505200, "nse": "EICHERMOT",   "screener": "eicher-motors",                   "ir": "https://www.eichermotors.com/investor-relations/annual-reports.aspx"},
    "GRASIM":     {"bse": 500300, "nse": "GRASIM",      "screener": "grasim-industries",               "ir": "https://www.grasim.com/investor-relations/annual-report"},
    "HCLTECH":    {"bse": 532281, "nse": "HCLTECH",     "screener": "hcl-technologies",                "ir": "https://www.hcltech.com/investors/annual-report"},
    "HDFCBANK":   {"bse": 500180, "nse": "HDFCBANK",    "screener": "hdfc-bank",                       "ir": "https://www.hdfcbank.com/content/bbp/repositories/723fb80a-2dde-42a3-9793-7ae1be57c87f/?folder=Investor+Relations/Annual+Reports"},
    "HDFCLIFE":   {"bse": 540777, "nse": "HDFCLIFE",    "screener": "hdfc-life-insurance-company",     "ir": "https://www.hdfclife.com/investor-relations/annual-reports"},
    "HEROMOTOCO": {"bse": 500182, "nse": "HEROMOTOCO",  "screener": "hero-motocorp",                   "ir": "https://www.heromotocorp.com/en-in/investors/annual-reports.html"},
    "HINDPETRO":  {"bse": 500104, "nse": "HINDPETRO",   "screener": "hindustan-petroleum-corporation", "ir": "https://www.hindustanpetroleum.com/annual-reports"},
    "HINDUNILVR": {"bse": 500696, "nse": "HINDUNILVR",  "screener": "hindustan-unilever",              "ir": "https://www.hul.co.in/investor-relations/annual-reports-and-accounts/"},
    "ICICIBANK":  {"bse": 532174, "nse": "ICICIBANK",   "screener": "icici-bank",                      "ir": "https://www.icicibank.com/aboutus/annual.page"},
    "ICICIPRULI": {"bse": 540133, "nse": "ICICIPRULI",  "screener": "icici-prudential-life-insurance", "ir": "https://www.iciciprulife.com/investor-relations/annual-reports.html"},
    "INDUSINDBK": {"bse": 532187, "nse": "INDUSINDBK",  "screener": "indusind-bank",                   "ir": "https://www.indusind.com/iblgspsite/investor-relations/annual-reports.html"},
    "INFY":       {"bse": 500209, "nse": "INFY",        "screener": "infosys",                         "ir": "https://www.infosys.com/investors/reports-filings/annual-report/annual/"},
    "ITC":        {"bse": 500875, "nse": "ITC",         "screener": "itc",                             "ir": "https://www.itcportal.com/investor/report-accounts.aspx"},
    "JSWSTEEL":   {"bse": 500228, "nse": "JSWSTEEL",    "screener": "jsw-steel",                       "ir": "https://www.jsw.in/investors/jsw-steel/annual-reports"},
    "KOTAKBANK":  {"bse": 500247, "nse": "KOTAKBANK",   "screener": "kotak-mahindra-bank",             "ir": "https://www.kotak.com/en/investor-relations/annual-reports.html"},
    "LT":         {"bse": 500510, "nse": "LT",          "screener": "larsen-and-toubro",               "ir": "https://www.larsentoubro.com/investor-relations/reports-filings/annual-reports/"},
    "M&M":        {"bse": 500520, "nse": "M&M",         "screener": "mahindra-and-mahindra",           "ir": "https://www.mahindra.com/investor-relations/annual-reports"},
    "MARUTI":     {"bse": 532500, "nse": "MARUTI",      "screener": "maruti-suzuki-india",             "ir": "https://www.marutisuzuki.com/corporate/investors/annual-reports"},
    "NESTLEIND":  {"bse": 500790, "nse": "NESTLEIND",   "screener": "nestle-india",                    "ir": "https://www.nestle.in/investors/annual-reports"},
    "NTPC":       {"bse": 532555, "nse": "NTPC",        "screener": "ntpc",                            "ir": "https://www.ntpc.co.in/en/investor-relations/annual-reports"},
    "ONGC":       {"bse": 500312, "nse": "ONGC",        "screener": "oil-and-natural-gas-corporation", "ir": "https://www.ongcindia.com/web/eng/annual-reports"},
    "POWERGRID":  {"bse": 532898, "nse": "POWERGRID",   "screener": "power-grid-corporation-of-india", "ir": "https://www.powergridindia.com/investor-relations/annual-report"},
    "RELIANCE":   {"bse": 500325, "nse": "RELIANCE",    "screener": "reliance-industries",             "ir": "https://www.ril.com/investor-relations/financial-reporting/annual-reports"},
    "SBIN":       {"bse": 500112, "nse": "SBIN",        "screener": "state-bank-of-india",             "ir": "https://www.sbi.co.in/web/investor-relations/annual-reports"},
    "SBILIFE":    {"bse": 540719, "nse": "SBILIFE",     "screener": "sbi-life-insurance-company",      "ir": "https://www.sbilife.co.in/en/investor-relations/annual-reports"},
    "SHREECEM":   {"bse": 500387, "nse": "SHREECEM",    "screener": "shree-cements",                   "ir": "https://www.shreecement.com/investor-relations/annual-reports"},
    "SUNPHARMA":  {"bse": 524715, "nse": "SUNPHARMA",   "screener": "sun-pharmaceutical-industries",   "ir": "https://www.sunpharma.com/investors/annual-reports"},
    "TATACONSUM": {"bse": 500800, "nse": "TATACONSUM",  "screener": "tata-consumer-products",          "ir": "https://www.tataconsumer.com/investors/annual-reports"},
    "TATAMOTORS": {"bse": 500570, "nse": "TATAMOTORS",  "screener": "tata-motors",                     "ir": "https://www.tatamotors.com/investors/annual-reports/"},
    "TATASTEEL":  {"bse": 500470, "nse": "TATASTEEL",   "screener": "tata-steel",                      "ir": "https://www.tatasteel.com/investors/annual-reports/"},
    "TCS":        {"bse": 532540, "nse": "TCS",         "screener": "tata-consultancy-services",       "ir": "https://www.tcs.com/investor-relations/financial-reports/annual-reports"},
    "TECHM":      {"bse": 532755, "nse": "TECHM",       "screener": "tech-mahindra",                   "ir": "https://www.techmahindra.com/en-in/investors/annual-reports/"},
    "TITAN":      {"bse": 500114, "nse": "TITAN",       "screener": "titan-company",                   "ir": "https://www.titancompany.in/investors/annual-reports"},
    "ULTRACEMCO": {"bse": 532538, "nse": "ULTRACEMCO",  "screener": "ultratech-cement",                "ir": "https://www.ultratechcement.com/investors/annual-reports"},
    "WIPRO":      {"bse": 507685, "nse": "WIPRO",       "screener": "wipro",                           "ir": "https://www.wipro.com/investors/annual-reports/"},
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

SOURCE_PRIORITY = {"BSE": 0, "NSE": 1, "Company IR": 2, "Screener": 3}


# ── Source 1 — BSE ───────────────────────────────────────────────────────────
def fetch_bse(bse_code, from_year, to_year):
    url = "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport/w"
    params = {"scripcode": bse_code, "type": "C", "Yrfrom": from_year, "Yrto": to_year}
    h = {**HEADERS, "Referer": "https://www.bseindia.com/"}
    try:
        r = requests.get(url, params=params, headers=h, timeout=15)
        r.raise_for_status()
        results = []
        for item in r.json().get("Table", []):
            year = str(item.get("year", ""))
            fname = item.get("file_name", "").lstrip("\\")
            if not fname or not year:
                continue
            try:
                yr_int = int(year)
            except ValueError:
                continue
            if not (from_year <= yr_int <= to_year):
                continue
            if fname.endswith(".pdf.pdf"):
                fname = fname[:-4]
            if re.match(r"[0-9a-f\-]{30,}", fname.split(".")[0]):
                link = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{fname}"
            else:
                link = f"https://www.bseindia.com/bseplus/AnnualReport/{bse_code}/{fname}"
            results.append({"year": year, "url": link, "source": "BSE"})
        return results
    except Exception:
        return []


# ── Source 2 — NSE ───────────────────────────────────────────────────────────
def fetch_nse(nse_symbol, from_year, to_year):
    base = "https://www.nseindia.com"
    session = requests.Session()
    session.headers.update({**HEADERS, "Referer": base + "/"})
    try:
        session.get(base, timeout=10)
        time.sleep(0.4)
        r = session.get(f"{base}/api/annual-reports?index={nse_symbol}", timeout=15)
        r.raise_for_status()
        results = []
        for item in r.json().get("data", []):
            year_str = item.get("year", "")
            try:
                year_end = int(year_str.split("-")[0]) + 1
            except Exception:
                year_end = 0
            if from_year <= year_end <= to_year:
                link = item.get("fileName", "")
                if link:
                    if not link.startswith("http"):
                        link = base + link
                    results.append({"year": year_str, "url": link, "source": "NSE"})
        return results
    except Exception:
        return []


# ── Source 3 — Screener.in ───────────────────────────────────────────────────
def fetch_screener(slug, from_year, to_year):
    url = f"https://www.screener.in/company/{slug}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        results = []
        seen_years = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if "Financial Year" not in text and "annual" not in text.lower():
                continue
            if not (href.endswith(".pdf") or "AnnualReport" in href or "annual_report" in href.lower() or "AttachHis" in href):
                continue
            ym = re.search(r"(20\d{2})", text + " " + href)
            if not ym:
                continue
            year = int(ym.group(1))
            if not (from_year <= year <= to_year):
                continue
            if year in seen_years:
                continue
            seen_years.add(year)
            if href.startswith("//"):
                href = "https:" + href
            elif not href.startswith("http"):
                href = "https://www.screener.in" + href
            results.append({"year": str(year), "url": href, "source": "Screener"})
        return results
    except Exception:
        return []


# ── Source 4 — Company IR page ───────────────────────────────────────────────
def fetch_ir(ir_url, from_year, to_year):
    try:
        r = requests.get(ir_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        results = []
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            combined = (href + " " + text).lower()
            if ".pdf" not in combined and "annual" not in combined:
                continue
            ym = re.search(r"(20\d{2})", href + " " + text)
            if not ym:
                continue
            year = int(ym.group(1))
            if not (from_year <= year <= to_year):
                continue
            if href.startswith("//"):
                href = "https:" + href
            elif not href.startswith("http"):
                href = urljoin(ir_url, href)
            if href in seen_urls:
                continue
            seen_urls.add(href)
            results.append({"year": str(year), "url": href, "source": "Company IR"})
        return results
    except Exception:
        return []


# ── PDF Downloader ───────────────────────────────────────────────────────────
_bse_session = None

def _get_bse_session():
    global _bse_session
    if _bse_session is None:
        _bse_session = requests.Session()
        _bse_session.headers.update({**HEADERS, "Referer": "https://www.bseindia.com/"})
        try:
            _bse_session.get("https://www.bseindia.com/", timeout=10)
        except Exception:
            pass
    return _bse_session


def download_pdf(url, dest):
    try:
        if "bseindia.com" in url:
            session = _get_bse_session()
            r = session.get(url, timeout=90, stream=True)
        else:
            r = requests.get(url, headers=HEADERS, timeout=90, stream=True)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "")
        if "pdf" not in ct.lower() and "octet-stream" not in ct.lower():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        if dest.stat().st_size < 10_000:
            dest.unlink()
            return False
        return True
    except Exception:
        if dest.exists():
            dest.unlink()
        return False


# ── Main ─────────────────────────────────────────────────────────────────────
def run(companies=None, from_year=2020, to_year=2025, delay=1.5):
    output_root = Path(ANNUAL_REPORTS_DIR)
    output_root.mkdir(parents=True, exist_ok=True)

    all_known = {**NIFTY50, **EXTRA_TICKERS}

    if companies:
        upper = [c.strip().upper() for c in companies]
        target = {k: v for k, v in all_known.items() if k in upper}
        missing = set(upper) - set(target.keys())
        if missing:
            print(f"WARNING: not found in registry: {missing}")
    else:
        target = NIFTY50

    print(f"\n{'='*62}")
    print(f"  NIFTY 50 Annual Report Downloader")
    print(f"  Companies : {len(target)}")
    print(f"  Period    : FY{from_year} to FY{to_year}")
    print(f"  Sources   : BSE -> NSE -> Screener.in -> Company IR")
    print(f"  Output    : {output_root.resolve()}")
    print(f"{'='*62}\n")

    log = []

    for symbol, meta in tqdm(target.items(), desc="Companies", unit="co"):
        print(f"\n[{symbol}]")

        all_reports = []

        print("  BSE ...", end=" ", flush=True)
        r1 = fetch_bse(meta["bse"], from_year, to_year)
        all_reports.extend(r1); print(len(r1))
        time.sleep(delay)

        print("  NSE ...", end=" ", flush=True)
        r2 = fetch_nse(meta["nse"], from_year, to_year)
        all_reports.extend(r2); print(len(r2))
        time.sleep(delay)

        print("  Screener ...", end=" ", flush=True)
        r3 = fetch_screener(meta["screener"], from_year, to_year)
        all_reports.extend(r3); print(len(r3))
        time.sleep(delay)

        print("  Company IR ...", end=" ", flush=True)
        r4 = fetch_ir(meta["ir"], from_year, to_year)
        all_reports.extend(r4); print(len(r4))
        time.sleep(delay)

        if not all_reports:
            print("  No reports found from any source.")
            log.append({"company": symbol, "year": "-", "source": "-", "status": "not found", "file": ""})
            continue

        best = {}
        for report in all_reports:
            yr = str(report["year"])
            p = SOURCE_PRIORITY.get(report["source"], 99)
            if yr not in best or p < SOURCE_PRIORITY.get(best[yr]["source"], 99):
                best[yr] = report

        for year, report in sorted(best.items()):
            url    = report["url"]
            source = report["source"]

            fname = f"{symbol}_AnnualReport_FY{year}.pdf"
            dest  = output_root / symbol / fname

            if dest.exists():
                print(f"  [EXISTS] {fname}")
                log.append({"company": symbol, "year": year, "source": source,
                            "status": "already exists", "file": str(dest)})
                continue

            print(f"  [DL] {fname} [{source}]...", end=" ", flush=True)
            ok = download_pdf(url, dest)
            if ok:
                size_kb = dest.stat().st_size // 1024
                print(f"OK ({size_kb} KB)")
                log.append({"company": symbol, "year": year, "source": source,
                            "status": "downloaded", "file": str(dest)})
            else:
                print("FAILED")
                log.append({"company": symbol, "year": year, "source": source,
                            "status": "failed", "file": ""})
            time.sleep(delay)

    df = pd.DataFrame(log)
    summary_path = output_root / "download_summary.csv"
    df.to_csv(summary_path, index=False)

    print(f"\n{'='*62}")
    print(f"  Downloaded      : {(df['status']=='downloaded').sum()}")
    print(f"  Already existed : {(df['status']=='already exists').sum()}")
    print(f"  Failed          : {(df['status']=='failed').sum()}")
    print(f"  Not found       : {(df['status']=='not found').sum()}")
    print(f"  Summary CSV     : {summary_path.resolve()}")
    print(f"{'='*62}\n")

    return df
