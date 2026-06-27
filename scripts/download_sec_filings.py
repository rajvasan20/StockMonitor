"""
Download 10-K / 20-F annual filings from SEC EDGAR for US pharma companies.
Saves PDFs (or HTML converted) to data/annual_reports/{TICKER}/
"""

import requests
import time
import os
import json
from pathlib import Path

# SEC EDGAR requires a User-Agent with company name and email
HEADERS = {
    "User-Agent": "StockMonitor vinoth.rajapandian@zoomrx.com",
    "Accept-Encoding": "gzip, deflate",
}

BASE_DIR = Path(r"C:\Users\VinothRajapandian\Personal Claude\Stock Monitor\data\annual_reports")

# Company configurations
COMPANIES = {
    "PFE": {"name": "Pfizer Inc", "cik": "0000078003", "form": "10-K"},
    "MRK": {"name": "Merck & Co Inc", "cik": "0000310158", "form": "10-K"},
    "NVS": {"name": "Novartis AG", "cik": "0001114448", "form": "20-F"},
    "AZN": {"name": "AstraZeneca PLC", "cik": "0000901832", "form": "20-F"},
    "LLY": {"name": "Eli Lilly and Co", "cik": "0000059478", "form": "10-K"},
}

# We want filings for fiscal years 2020-2024 (last 5 completed years)
# FY2025 10-Ks won't be filed until early 2026 for calendar-year companies
TARGET_YEARS = [2020, 2021, 2022, 2023, 2024]


def get_company_filings(cik: str) -> dict:
    """Fetch filing index from SEC EDGAR submissions API."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def find_annual_filings(data: dict, form_type: str, target_years: list) -> list:
    """Extract 10-K or 20-F filings for target years from EDGAR submissions data."""
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    filings = []
    for i, form in enumerate(forms):
        # Match exact form type (10-K, not 10-K/A; 20-F, not 20-F/A)
        if form != form_type:
            continue

        report_year = int(report_dates[i][:4]) if report_dates[i] else None
        filing_year = int(dates[i][:4]) if dates[i] else None

        # For 10-K: report date year is the fiscal year
        # For 20-F: similar logic
        fy = report_year

        if fy in target_years:
            accession_clean = accessions[i].replace("-", "")
            filings.append({
                "fy": fy,
                "filing_date": dates[i],
                "report_date": report_dates[i],
                "accession": accessions[i],
                "accession_clean": accession_clean,
                "primary_doc": primary_docs[i],
                "form": form,
            })

    return filings


def get_filing_documents(cik: str, accession_clean: str) -> list:
    """Get the list of documents in a filing to find the best PDF."""
    url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}/index.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def download_file(url: str, save_path: Path) -> bool:
    """Download a file from SEC EDGAR."""
    resp = requests.get(url, headers=HEADERS, stream=True)
    if resp.status_code == 200:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = save_path.stat().st_size / (1024 * 1024)
        print(f"  [OK] Saved: {save_path.name} ({size_mb:.1f} MB)")
        return True
    else:
        print(f"  [FAIL] ({resp.status_code}): {url}")
        return False


def find_best_document(cik: str, filing: dict) -> tuple:
    """Find the best document to download - prefer PDF, fallback to HTML."""
    cik_num = cik.lstrip("0")
    accession_clean = filing["accession_clean"]
    primary_doc = filing["primary_doc"]

    # First, try the filing index to find PDF versions
    try:
        index_data = get_filing_documents(cik, accession_clean)
        time.sleep(0.15)  # Rate limit

        items = index_data.get("directory", {}).get("item", [])

        # Look for PDF files
        pdf_files = [item for item in items if item.get("name", "").lower().endswith(".pdf")]

        # Prefer the largest PDF (usually the full filing)
        if pdf_files:
            pdf_files.sort(key=lambda x: int(x.get("size", "0").replace(",", "") if x.get("size") else "0"), reverse=True)
            best_pdf = pdf_files[0]["name"]
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{best_pdf}"
            return url, best_pdf, "pdf"
    except Exception as e:
        print(f"  Warning: Could not fetch filing index: {e}")

    # Fallback to primary document (usually HTML)
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{primary_doc}"
    return url, primary_doc, "html" if primary_doc.endswith(".htm") or primary_doc.endswith(".html") else "other"


def process_company(ticker: str, config: dict):
    """Download all annual filings for a company."""
    print(f"\n{'='*60}")
    print(f"Processing {ticker} ({config['name']}) — Form {config['form']}")
    print(f"{'='*60}")

    # Get filing list
    print(f"Fetching filings for CIK {config['cik']}...")
    data = get_company_filings(config["cik"])
    time.sleep(0.15)

    filings = find_annual_filings(data, config["form"], TARGET_YEARS)
    print(f"Found {len(filings)} {config['form']} filings for years {TARGET_YEARS}")

    if not filings:
        # Check older filings if not in recent
        older_files = data.get("filings", {}).get("files", [])
        if older_files:
            print(f"  Note: {len(older_files)} older filing batches exist, may need separate fetch")

    results = []
    for filing in sorted(filings, key=lambda x: x["fy"]):
        fy = filing["fy"]
        out_dir = BASE_DIR / ticker
        out_dir.mkdir(parents=True, exist_ok=True)

        # Check if already downloaded
        existing = list(out_dir.glob(f"{ticker}_AnnualReport_FY{fy}.*"))
        if existing:
            print(f"  FY{fy}: Already exists — {existing[0].name}")
            results.append({"fy": fy, "status": "exists", "file": existing[0].name})
            continue

        print(f"  FY{fy}: Finding best document...")
        url, doc_name, doc_type = find_best_document(config["cik"], filing)
        time.sleep(0.15)

        ext = "pdf" if doc_type == "pdf" else Path(doc_name).suffix.lstrip(".")
        save_name = f"{ticker}_AnnualReport_FY{fy}.{ext}"
        save_path = out_dir / save_name

        print(f"  FY{fy}: Downloading {doc_type.upper()} — {doc_name}")
        success = download_file(url, save_path)
        time.sleep(0.15)

        results.append({
            "fy": fy,
            "status": "downloaded" if success else "failed",
            "file": save_name,
            "url": url,
            "type": doc_type,
        })

    return results


def main():
    all_results = {}
    for ticker, config in COMPANIES.items():
        try:
            results = process_company(ticker, config)
            all_results[ticker] = results
        except Exception as e:
            print(f"ERROR processing {ticker}: {e}")
            all_results[ticker] = [{"status": "error", "error": str(e)}]

    # Summary
    print(f"\n{'='*60}")
    print("DOWNLOAD SUMMARY")
    print(f"{'='*60}")
    for ticker, results in all_results.items():
        downloaded = sum(1 for r in results if r.get("status") == "downloaded")
        existing = sum(1 for r in results if r.get("status") == "exists")
        failed = sum(1 for r in results if r.get("status") == "failed")
        print(f"  {ticker}: {downloaded} downloaded, {existing} existing, {failed} failed")


if __name__ == "__main__":
    main()
