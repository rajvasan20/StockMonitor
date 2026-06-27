"""
Download DEF 14A (proxy statements) from SEC EDGAR for US pharma companies.
"""

import requests
import time
from pathlib import Path

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

TARGET_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


def get_company_filings(cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def download_file(url: str, save_path: Path) -> bool:
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


def process_company(ticker: str, config: dict):
    cik = config["cik"]
    print(f"\n{'='*50}")
    print(f"{ticker} ({config['name']})")
    print(f"{'='*50}")

    data = get_company_filings(cik)
    time.sleep(0.2)

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    # Also check older filings
    older_files = data.get("filings", {}).get("files", [])
    for older in older_files:
        fname = older.get("name", "")
        if not fname:
            continue
        try:
            url = f"https://data.sec.gov/submissions/{fname}"
            resp = requests.get(url, headers=HEADERS)
            resp.raise_for_status()
            older_data = resp.json()
            time.sleep(0.2)
            forms.extend(older_data.get("form", []))
            dates.extend(older_data.get("filingDate", []))
            accessions.extend(older_data.get("accessionNumber", []))
            primary_docs.extend(older_data.get("primaryDocument", []))
        except Exception as e:
            print(f"  Warning: {fname}: {e}")

    out_dir = BASE_DIR / ticker / "DEF14A"
    out_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    existing = 0
    for i, form in enumerate(forms):
        if form != "DEF 14A":
            continue

        filing_year = int(dates[i][:4]) if dates[i] else None
        if filing_year not in TARGET_YEARS:
            continue

        accession_clean = accessions[i].replace("-", "")
        cik_num = cik.lstrip("0")
        primary_doc = primary_docs[i]

        save_name = f"{ticker}_DEF14A_{dates[i]}.htm"
        save_path = out_dir / save_name

        if save_path.exists():
            print(f"    Already exists: {save_name}")
            existing += 1
            continue

        url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{primary_doc}"
        if download_file(url, save_path):
            downloaded += 1
        time.sleep(0.3)

    print(f"  Result: {downloaded} downloaded, {existing} existing")
    return downloaded, existing


def main():
    summary = {}
    for ticker, config in COMPANIES.items():
        try:
            dl, ex = process_company(ticker, config)
            summary[ticker] = {"downloaded": dl, "existing": ex}
        except Exception as e:
            print(f"  ERROR: {e}")
            summary[ticker] = {"error": str(e)}

    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    for ticker, r in summary.items():
        if "error" in r:
            print(f"  {ticker}: ERROR - {r['error']}")
        else:
            print(f"  {ticker}: {r['downloaded']} downloaded, {r['existing']} existing")


if __name__ == "__main__":
    main()
