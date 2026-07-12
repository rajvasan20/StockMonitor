"""Screener.in HTML scraper with rate limiting and retries."""

import time
import random
import requests
from config import (
    SCREENER_BASE_URL, REQUEST_DELAY_SECONDS, REQUEST_DELAY_JITTER,
    MAX_RETRIES, RETRY_BACKOFF_FACTOR, REQUEST_TIMEOUT,
)
from shared.utils import logger


class ScreenerScraper:
    """Rate-limited scraper for Screener.in company pages."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self._last_request_time = 0

    def _rate_limit(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        delay = REQUEST_DELAY_SECONDS + random.uniform(0, REQUEST_DELAY_JITTER)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_time = time.time()

    def _get_with_retry(self, url):
        """GET with exponential backoff. Returns response or None."""
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)

                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 404:
                    return None  # Not on Screener
                elif resp.status_code == 429:
                    wait = RETRY_BACKOFF_FACTOR ** attempt * 30
                    logger.warning(f"Rate limited on {url}, waiting {wait}s")
                    time.sleep(wait)
                else:
                    logger.warning(f"HTTP {resp.status_code} for {url}")
                    time.sleep(RETRY_BACKOFF_FACTOR ** attempt * 5)

            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error for {url}: {e}")
                time.sleep(RETRY_BACKOFF_FACTOR ** attempt * 5)

        logger.error(f"All retries exhausted for {url}")
        return None

    def fetch_company_html(self, ticker):
        """Fetch raw HTML for a ticker. Tries consolidated first, then standalone.
        Falls back to standalone if consolidated page has no financial data.
        Returns (html_string, variant) or (None, None).
        """
        for variant in ["consolidated", ""]:
            url = SCREENER_BASE_URL.format(ticker=ticker, variant=variant)
            resp = self._get_with_retry(url)
            if resp is not None:
                html = resp.text
                # Check if page has actual financial data (not just empty structure)
                if variant == "consolidated" and not self._has_financial_data(html):
                    logger.info(f"{ticker}: Consolidated page has no data, trying standalone")
                    continue
                return html, variant or "standalone"
        return None, None

    @staticmethod
    def _has_financial_data(html):
        """Check if HTML contains actual financial data values."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        section = soup.find("section", id="profit-loss")
        if not section:
            return False
        table = section.find("table")
        if not table:
            return False
        rows = table.find_all("tr")
        if len(rows) < 2:
            return False
        # Check if header row has year columns
        header_cells = rows[0].find_all(["th", "td"])
        year_texts = [c.get_text(strip=True) for c in header_cells[1:] if c.get_text(strip=True)]
        return len(year_texts) > 0
