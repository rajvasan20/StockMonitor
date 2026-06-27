"""
Download DEF 14A (proxy statements) and Form 4 (insider transactions)
from SEC EDGAR for US pharma companies.
"""

import requests
import time
import os
import json
from pathlib import Path
from datetime import datetime

HEADERS = {
    "User-Agent": "StockMonitor vinoth.rajapandian@zoomrx.com",
    "Accept-Encoding": "gzip, deflate",
}

BASE_DIR = Path(r"C:\Users\VinothRajapandian\Personal Claude\Stock Monitor\data\annual_reports")

COMPANIES = {
    "PFE": {"name": "Pfizer Inc", "cik": "0000078003"},
    "MRK": {"name": "Merck & Co Inc", "cik": "0000310158"},
    "NVS": {"name": "Novartis AG", "cik": "0001114448"},
    "AZN": {"name": "AstraZeneca PLC", "cik": "0000901832"},
    "LLY": {"name": "Eli Lilly and Co", "cik": "0000059478"},
}

TARGET_YEARS = [2020, 2021, 2022, 2023, 2024]


def get_company_filings(cik: str) -> dict:
    """Fetch filing index from SEC EDGAR submissions API."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def get_older_filings(cik: str, older_file: str) -> dict:
    """Fetch older filings batch."""
    url = f"https://data.sec.gov/submissions/{older_file}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def collect_all_filings(data: dict, cik: str) -> dict:
    """Combine recent + older filing batches into one structure."""
    recent = data.get("filings", {}).get("recent", {})
    forms = list(recent.get("form", []))
    dates = list(recent.get("filingDate", []))
    accessions = list(recent.get("accessionNumber", []))
    primary_docs = list(recent.get("primaryDocument", []))
    report_dates = list(recent.get("reportDate", []))

    # Check if we need older filings
    older_files = data.get("filings", {}).get("files", [])
    for older in older_files:
        fname = older.get("name", "")
        if not fname:
            continue
        try:
            older_data = get_older_filings(cik, fname)
            time.sleep(0.15)
            forms.extend(older_data.get("form", []))
            dates.extend(older_data.get("filingDate", []))
            accessions.extend(older_data.get("accessionNumber", []))
            primary_docs.extend(older_data.get("primaryDocument", []))
            report_dates.extend(older_data.get("reportDate", []))
        except Exception as e:
            print(f"  Warning: Could not fetch older filings {fname}: {e}")

    return {
        "form": forms,
        "filingDate": dates,
        "accessionNumber": accessions,
        "primaryDocument": primary_docs,
        "reportDate": report_dates,
    }


def download_file(url: str, save_path: Path) -> bool:
    """Download a file from SEC EDGAR."""
    resp = requests.get(url, headers=HEADERS, stream=True)
    if resp.status_code == 200:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_kb = save_path.stat().st_size / 1024
        print(f"    [OK] {save_path.name} ({size_kb:.0f} KB)")
        return True
    else:
        print(f"    [FAIL] ({resp.status_code}): {url}")
        return False


def download_def14a(ticker: str, cik: str, all_filings: dict):
    """Download DEF 14A proxy statements for target years."""
    print(f"\n  --- DEF 14A (Proxy Statements) ---")

    out_dir = BASE_DIR / ticker / "DEF14A"
    out_dir.mkdir(parents=True, exist_ok=True)

    forms = all_filings["form"]
    dates = all_filings["filingDate"]
    accessions = all_filings["accessionNumber"]
    primary_docs = all_filings["primaryDocument"]

    found = 0
    for i, form in enumerate(forms):
        if form != "DEF 14A":
            continue

        filing_year = int(dates[i][:4]) if dates[i] else None
        if filing_year not in TARGET_YEARS and filing_year not in [y + 1 for y in TARGET_YEARS]:
            continue

        # DEF 14A is typically filed in the year after the fiscal year it covers
        # e.g., FY2023 proxy filed in early 2024
        # Use filing year for naming
        fy_label = filing_year

        accession_clean = accessions[i].replace("-", "")
        cik_num = cik.lstrip("0")
        primary_doc = primary_docs[i]

        save_name = f"{ticker}_DEF14A_{dates[i]}.htm"
        save_path = out_dir / save_name

        if save_path.exists():
            print(f"    Already exists: {save_name}")
            found += 1
            continue

        url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{primary_doc}"
        if download_file(url, save_path):
            found += 1
        time.sleep(0.15)

    print(f"  DEF 14A total: {found} files")
    return found


def download_form4(ticker: str, cik: str, all_filings: dict):
    """Download Form 4 insider transaction filings for target years."""
    print(f"\n  --- Form 4 (Insider Transactions) ---")

    out_dir = BASE_DIR / ticker / "Form4"
    out_dir.mkdir(parents=True, exist_ok=True)

    forms = all_filings["form"]
    dates = all_filings["filingDate"]
    accessions = all_filings["accessionNumber"]
    primary_docs = all_filings["primaryDocument"]

    # Collect all Form 4 filings in target years
    form4_filings = []
    for i, form in enumerate(forms):
        if form != "4":
            continue
        filing_year = int(dates[i][:4]) if dates[i] else None
        if filing_year and filing_year in TARGET_YEARS:
            form4_filings.append({
                "date": dates[i],
                "accession": accessions[i],
                "primary_doc": primary_docs[i],
            })

    print(f"  Found {len(form4_filings)} Form 4 filings in {TARGET_YEARS}")

    # Download all
    downloaded = 0
    skipped = 0
    for f4 in form4_filings:
        accession_clean = f4["accession"].replace("-", "")
        cik_num = cik.lstrip("0")

        save_name = f"{ticker}_Form4_{f4['date']}_{accession_clean[-8:]}.htm"
        save_path = out_dir / save_name

        if save_path.exists():
            skipped += 1
            continue

        url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{f4['primary_doc']}"
        if download_file(url, save_path):
            downloaded += 1
        time.sleep(0.12)  # Stay within rate limits

    print(f"  Form 4 total: {downloaded} downloaded, {skipped} existing")
    return downloaded


def process_company(ticker: str, config: dict):
    """Download DEF 14A and Form 4 for a company."""
    print(f"\n{'='*60}")
    print(f"{ticker} ({config['name']})")
    print(f"{'='*60}")

    cik = config["cik"]
    print(f"Fetching all filings for CIK {cik}...")
    data = get_company_filings(cik)
    time.sleep(0.15)

    all_filings = collect_all_filings(data, cik)
    total_forms = len(all_filings["form"])
    print(f"Total filings indexed: {total_forms}")

    # Count what's available
    form_counts = {}
    for f in all_filings["form"]:
        form_counts[f] = form_counts.get(f, 0) + 1

    def14a_count = form_counts.get("DEF 14A", 0)
    form4_count = form_counts.get("4", 0)
    print(f"DEF 14A filings: {def14a_count} total | Form 4 filings: {form4_count} total")

    def14a_result = download_def14a(ticker, cik, all_filings)
    form4_result = download_form4(ticker, cik, all_filings)

    return def14a_result, form4_result


def main():
    summary = {}
    for ticker, config in COMPANIES.items():
        try:
            def14a, form4 = process_company(ticker, config)
            summary[ticker] = {"DEF14A": def14a, "Form4": form4}
        except Exception as e:
            print(f"ERROR processing {ticker}: {e}")
            import traceback
            traceback.print_exc()
            summary[ticker] = {"error": str(e)}

    print(f"\n{'='*60}")
    print("DOWNLOAD SUMMARY")
    print(f"{'='*60}")
    for ticker, result in summary.items():
        if "error" in result:
            print(f"  {ticker}: ERROR - {result['error']}")
        else:
            print(f"  {ticker}: DEF 14A={result['DEF14A']} files, Form 4={result['Form4']} files")


if __name__ == "__main__":
    main()
