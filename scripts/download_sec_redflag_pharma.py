"""
Download DEF 14A proxy statements from SEC EDGAR for pharma companies
with known governance/integrity concerns — for CANDOR contrast analysis.
"""

import requests
import time
from pathlib import Path

HEADERS = {
    "User-Agent": "StockMonitor vinoth.rajapandian@zoomrx.com",
    "Accept-Encoding": "gzip, deflate",
}

BASE_DIR = Path(r"C:\Users\VinothRajapandian\Personal Claude\Stock Monitor\CANDOR")

# Companies with known governance issues
# Note: Some may have limited filings due to bankruptcy/delisting
COMPANIES = {
    "MNK": {"name": "Mallinckrodt Pharmaceuticals", "cik": "0001145951", "notes": "Bankrupt twice (2020, 2023) - opioid litigation"},
    "ENDP": {"name": "Endo International", "cik": "0001593034", "notes": "Bankrupt 2022 - opioid litigation; now Endo Inc."},
    "TEVA": {"name": "Teva Pharmaceutical Industries", "cik": "0000818686", "notes": "FCPA settlement, price-fixing allegations"},
    "INDV": {"name": "Indivior PLC", "cik": "0001618921", "notes": "Opioid marketing misconduct, criminal penalties"},
    "CTLT": {"name": "Catalent Inc", "cik": "0001596783", "notes": "Accounting concerns, securities litigation; acquired by Novo Holdings 2024"},
}

TARGET_YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]


def get_company_filings(cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def get_older_filings(older_file: str) -> dict:
    url = f"https://data.sec.gov/submissions/{older_file}"
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
    print(f"\n{'='*60}")
    print(f"{ticker} ({config['name']})")
    print(f"Note: {config['notes']}")
    print(f"{'='*60}")

    try:
        data = get_company_filings(cik)
        time.sleep(0.2)
    except Exception as e:
        print(f"  ERROR fetching filings: {e}")
        return 0

    company_name = data.get("name", config["name"])
    print(f"  SEC Name: {company_name}")

    # Collect all filings (recent + older)
    forms = list(data.get("filings", {}).get("recent", {}).get("form", []))
    dates = list(data.get("filings", {}).get("recent", {}).get("filingDate", []))
    accessions = list(data.get("filings", {}).get("recent", {}).get("accessionNumber", []))
    primary_docs = list(data.get("filings", {}).get("recent", {}).get("primaryDocument", []))

    older_files = data.get("filings", {}).get("files", [])
    for older in older_files:
        fname = older.get("name", "")
        if not fname:
            continue
        try:
            older_data = get_older_filings(fname)
            time.sleep(0.2)
            forms.extend(older_data.get("form", []))
            dates.extend(older_data.get("filingDate", []))
            accessions.extend(older_data.get("accessionNumber", []))
            primary_docs.extend(older_data.get("primaryDocument", []))
        except Exception as e:
            print(f"  Warning: {fname}: {e}")

    # Find DEF 14A filings
    # Also look for DEFA14A (additional proxy materials) and PRE 14A (preliminary)
    proxy_types = ["DEF 14A", "DEFA14A", "PRE 14A"]

    out_dir = BASE_DIR / ticker / "DEF14A"
    out_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    found_forms = {}

    for i, form in enumerate(forms):
        if form not in proxy_types:
            continue

        filing_year = int(dates[i][:4]) if dates[i] else None
        if filing_year not in TARGET_YEARS:
            continue

        # Track what we find
        key = f"{form}_{dates[i]}"
        if key in found_forms:
            continue
        found_forms[key] = True

        accession_clean = accessions[i].replace("-", "")
        cik_num = cik.lstrip("0")
        primary_doc = primary_docs[i]

        form_label = form.replace(" ", "")
        save_name = f"{ticker}_{form_label}_{dates[i]}.htm"
        save_path = out_dir / save_name

        if save_path.exists():
            print(f"    Already exists: {save_name}")
            downloaded += 1
            continue

        url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{primary_doc}"
        if download_file(url, save_path):
            downloaded += 1
        time.sleep(0.3)

    if downloaded == 0:
        print(f"  No DEF 14A / DEFA14A / PRE 14A filings found in {TARGET_YEARS}")
        # Check what filing types exist
        form_counts = {}
        for f in forms:
            form_counts[f] = form_counts.get(f, 0) + 1
        proxy_related = {k: v for k, v in form_counts.items() if "14" in k or "proxy" in k.lower()}
        if proxy_related:
            print(f"  Proxy-related filings found: {proxy_related}")
        else:
            print(f"  All filing types: {dict(list(sorted(form_counts.items(), key=lambda x: -x[1]))[:10])}")

    return downloaded


def main():
    summary = {}
    for ticker, config in COMPANIES.items():
        count = process_company(ticker, config)
        summary[ticker] = count

    print(f"\n{'='*60}")
    print("DOWNLOAD SUMMARY")
    print(f"{'='*60}")
    for ticker, count in summary.items():
        status = f"{count} files" if count > 0 else "NONE FOUND"
        print(f"  {ticker} ({COMPANIES[ticker]['name']}): {status}")


if __name__ == "__main__":
    main()
