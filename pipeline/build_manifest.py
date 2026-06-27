"""
Build extraction manifest — lists all PDF → JSON jobs with status tracking.
Run this first to generate manifest.json, then run batch_extract.py.
"""

import json
import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(r"C:/Users/VinothRajapandian/Personal Claude/Stock Monitor")
AR_DIR = PROJECT_ROOT / "data" / "annual_reports"
MANIFEST_PATH = PROJECT_ROOT / "pipeline" / "manifest.json"


def build_manifest():
    jobs = []

    # Find all annual report PDFs
    for ticker_dir in sorted(AR_DIR.iterdir()):
        if not ticker_dir.is_dir() or ticker_dir.name.startswith("_"):
            continue

        ticker = ticker_dir.name

        for pdf in sorted(ticker_dir.glob(f"{ticker}_AnnualReport_FY*.pdf")):
            # Extract year from filename: TICKER_AnnualReport_FY2025.pdf
            fy = pdf.stem.split("_FY")[-1]  # "2025"
            fy_label = f"FY{fy}"

            # Check if JSON already exists
            json_path = ticker_dir / f"{ticker}_Notes_{fy_label}.json"

            jobs.append({
                "ticker": ticker,
                "fy": fy_label,
                "pdf": str(pdf),
                "json_output": str(json_path),
                "status": "done" if json_path.exists() else "pending",
                "started_at": None,
                "completed_at": str(datetime.now().isoformat()) if json_path.exists() else None,
                "error": None,
                "attempt": 1 if json_path.exists() else 0,
            })

    manifest = {
        "created": datetime.now().isoformat(),
        "total_jobs": len(jobs),
        "pending": sum(1 for j in jobs if j["status"] == "pending"),
        "done": sum(1 for j in jobs if j["status"] == "done"),
        "failed": 0,
        "jobs": jobs,
    }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Print summary
    tickers = set(j["ticker"] for j in jobs)
    print(f"Manifest built: {MANIFEST_PATH}")
    print(f"  Companies: {len(tickers)}")
    print(f"  Total PDFs: {manifest['total_jobs']}")
    print(f"  Already done: {manifest['done']}")
    print(f"  Pending: {manifest['pending']}")

    # Show per-company breakdown
    print(f"\nPer-company PDF count:")
    for t in sorted(tickers):
        count = sum(1 for j in jobs if j["ticker"] == t)
        done = sum(1 for j in jobs if j["ticker"] == t and j["status"] == "done")
        marker = " ✓" if done == count else f" ({done}/{count})"
        print(f"  {t}: {count} PDFs{marker}")


if __name__ == "__main__":
    build_manifest()
