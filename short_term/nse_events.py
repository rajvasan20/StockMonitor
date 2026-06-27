"""NSE event data — bulk deals, block deals, delivery %, insider trading.

Scrapes publicly available data from NSE archives. These are fundamental
triggers that, combined with technical signals, flag short-term opportunities.
"""

import re
import time
import random
import io
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import requests
import pandas as pd

from shared.utils import logger


# NSE requires specific headers to avoid 403
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


@dataclass
class BulkBlockDeal:
    date: str
    ticker: str
    client: str
    deal_type: str      # "BUY" or "SELL"
    quantity: int
    price: float
    source: str         # "bulk" or "block"


@dataclass
class DeliveryData:
    date: str
    ticker: str
    delivery_pct: float
    volume: int
    delivery_qty: int


@dataclass
class InsiderTrade:
    date: str
    ticker: str
    person: str
    category: str       # "Promoter", "Promoter Group", "Director"
    trade_type: str     # "BUY" or "SELL"
    quantity: int
    value: Optional[float] = None


@dataclass
class FundamentalTriggers:
    """Aggregated fundamental triggers for a ticker."""
    ticker: str
    # Bulk/block deals (recent)
    bulk_deals: List[BulkBlockDeal] = field(default_factory=list)
    net_bulk_buy: bool = False        # More buying than selling in bulk deals

    # Delivery percentage
    avg_delivery_pct: Optional[float] = None
    recent_delivery_pct: Optional[float] = None
    high_delivery: bool = False       # Recent delivery > 70%

    # Insider/promoter activity
    insider_trades: List[InsiderTrade] = field(default_factory=list)
    promoter_buying: bool = False

    # Combined
    trigger_count: int = 0
    triggers: List[str] = field(default_factory=list)


def _nse_session() -> requests.Session:
    """Create a session with NSE-compatible headers."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    # Hit the homepage first to get cookies
    try:
        session.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    return session


def _deals_to_dicts(deals: List[BulkBlockDeal]) -> List[dict]:
    """Serialize deals for JSON cache."""
    return [{"date": d.date, "ticker": d.ticker, "client": d.client,
             "deal_type": d.deal_type, "quantity": d.quantity,
             "price": d.price, "source": d.source} for d in deals]


def _dicts_to_deals(dicts: List[dict]) -> List[BulkBlockDeal]:
    """Deserialize deals from JSON cache."""
    return [BulkBlockDeal(**d) for d in dicts]


def fetch_bulk_deals(days_back: int = 30) -> List[BulkBlockDeal]:
    """Fetch recent bulk deals from NSE. Uses daily cache."""
    from shared.utils import daily_cache_get, daily_cache_set

    cached = daily_cache_get("bulk_deals")
    if cached is not None:
        return _dicts_to_deals(cached)

    deals = []
    session = _nse_session()

    try:
        url = "https://archives.nseindia.com/content/equities/bulk.csv"
        resp = session.get(url, timeout=15)

        if resp.status_code == 200 and resp.text.strip():
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

            for _, row in df.iterrows():
                try:
                    deals.append(BulkBlockDeal(
                        date=str(row.get("date", "")),
                        ticker=str(row.get("symbol", "")).strip(),
                        client=str(row.get("client_name", "")).strip(),
                        deal_type="BUY" if str(row.get("buy_/_sell", "")).upper().startswith("B") else "SELL",
                        quantity=int(float(row.get("quantity_traded", 0))),
                        price=float(row.get("trade_price_/_wt._avg._price", 0)),
                        source="bulk",
                    ))
                except (ValueError, TypeError):
                    continue

            logger.info(f"Fetched {len(deals)} bulk deals")
        else:
            logger.warning(f"Bulk deals: HTTP {resp.status_code}")

    except Exception as e:
        logger.error(f"Failed to fetch bulk deals: {e}")

    daily_cache_set("bulk_deals", _deals_to_dicts(deals))
    return deals


def fetch_block_deals() -> List[BulkBlockDeal]:
    """Fetch recent block deals from NSE. Uses daily cache."""
    from shared.utils import daily_cache_get, daily_cache_set

    cached = daily_cache_get("block_deals")
    if cached is not None:
        return _dicts_to_deals(cached)

    deals = []
    session = _nse_session()

    try:
        url = "https://archives.nseindia.com/content/equities/block.csv"
        resp = session.get(url, timeout=15)

        if resp.status_code == 200 and resp.text.strip():
            df = pd.read_csv(io.StringIO(resp.text))
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

            for _, row in df.iterrows():
                try:
                    deals.append(BulkBlockDeal(
                        date=str(row.get("date", "")),
                        ticker=str(row.get("symbol", "")).strip(),
                        client=str(row.get("client_name", "")).strip(),
                        deal_type="BUY" if str(row.get("buy_/_sell", "")).upper().startswith("B") else "SELL",
                        quantity=int(float(row.get("quantity_traded", 0))),
                        price=float(row.get("trade_price_/_wt._avg._price", 0)),
                        source="block",
                    ))
                except (ValueError, TypeError):
                    continue

            logger.info(f"Fetched {len(deals)} block deals")
        else:
            logger.warning(f"Block deals: HTTP {resp.status_code}")

    except Exception as e:
        logger.error(f"Failed to fetch block deals: {e}")

    daily_cache_set("block_deals", _deals_to_dicts(deals))
    return deals


def fetch_delivery_data(ticker: str, days: int = 20) -> List[DeliveryData]:
    """Fetch delivery percentage data for a ticker.

    Uses NSE equity bhavcopy from archives.
    """
    results = []
    session = _nse_session()

    # Try NSE API for delivery data
    try:
        url = f"https://www.nseindia.com/api/historical/securityArchives"
        params = {
            "from": (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y"),
            "to": datetime.now().strftime("%d-%m-%Y"),
            "symbol": ticker.upper(),
            "dataType": "priceVolumeDeliverable",
            "series": "EQ",
        }
        resp = session.get(url, params=params, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            for entry in data.get("data", []):
                try:
                    delivery_pct = float(entry.get("CH_TOT_TRADED_VAL", 0))
                    if "CH_DELIV_QTY" in entry and "CH_TOT_TRADED_QTY" in entry:
                        tot = float(entry["CH_TOT_TRADED_QTY"])
                        deliv = float(entry["CH_DELIV_QTY"])
                        if tot > 0:
                            delivery_pct = (deliv / tot) * 100

                    results.append(DeliveryData(
                        date=str(entry.get("CH_TIMESTAMP", "")),
                        ticker=ticker,
                        delivery_pct=delivery_pct,
                        volume=int(float(entry.get("CH_TOT_TRADED_QTY", 0))),
                        delivery_qty=int(float(entry.get("CH_DELIV_QTY", 0))),
                    ))
                except (ValueError, TypeError):
                    continue

    except Exception as e:
        logger.warning(f"Delivery data for {ticker}: {e}")

    return results


def fetch_insider_trades(ticker: str, days: int = 90) -> List[InsiderTrade]:
    """Fetch insider/promoter trading data.

    Attempts NSE corporate announcements API. Falls back gracefully.
    """
    trades = []
    session = _nse_session()

    try:
        url = "https://www.nseindia.com/api/corporates-pit"
        params = {
            "index": "equities",
            "from_date": (datetime.now() - timedelta(days=days)).strftime("%d-%m-%Y"),
            "to_date": datetime.now().strftime("%d-%m-%Y"),
            "symbol": ticker.upper(),
        }
        resp = session.get(url, params=params, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            for entry in data.get("data", []):
                try:
                    category = str(entry.get("personCategory", ""))
                    acq_disp = str(entry.get("acqMode", "")).upper()
                    qty_str = str(entry.get("securitiesValue", "0"))
                    qty = int(float(re.sub(r"[^0-9.]", "", qty_str) or "0"))

                    if "PROMOTER" in category.upper() or "DIRECTOR" in category.upper():
                        trades.append(InsiderTrade(
                            date=str(entry.get("date", "")),
                            ticker=ticker,
                            person=str(entry.get("acqName", "")),
                            category=category,
                            trade_type="BUY" if "BUY" in acq_disp or "ACQUISITION" in acq_disp else "SELL",
                            quantity=qty,
                        ))
                except (ValueError, TypeError):
                    continue

    except Exception as e:
        logger.warning(f"Insider trades for {ticker}: {e}")

    return trades


def get_fundamental_triggers(ticker: str,
                              bulk_deals: Optional[List[BulkBlockDeal]] = None,
                              block_deals: Optional[List[BulkBlockDeal]] = None,
                              ) -> FundamentalTriggers:
    """Aggregate all fundamental triggers for a ticker.

    Pre-fetched bulk/block deals can be passed to avoid repeated API calls
    when screening multiple tickers.
    """
    result = FundamentalTriggers(ticker=ticker)

    # ── Bulk/Block deals ─────────────────────────────────────────────────
    if bulk_deals is None:
        bulk_deals = fetch_bulk_deals()
    if block_deals is None:
        block_deals = fetch_block_deals()

    all_deals = bulk_deals + block_deals
    ticker_deals = [d for d in all_deals if d.ticker.upper() == ticker.upper()]
    result.bulk_deals = ticker_deals

    if ticker_deals:
        buy_qty = sum(d.quantity for d in ticker_deals if d.deal_type == "BUY")
        sell_qty = sum(d.quantity for d in ticker_deals if d.deal_type == "SELL")
        if buy_qty > sell_qty:
            result.net_bulk_buy = True
            result.triggers.append(
                f"Net bulk buying ({buy_qty:,} bought vs {sell_qty:,} sold)"
            )

    # ── Delivery percentage ──────────────────────────────────────────────
    delivery_data = fetch_delivery_data(ticker)
    if delivery_data:
        pcts = [d.delivery_pct for d in delivery_data if d.delivery_pct > 0]
        if pcts:
            result.avg_delivery_pct = sum(pcts) / len(pcts)
            result.recent_delivery_pct = pcts[-1] if pcts else None

            if result.recent_delivery_pct and result.recent_delivery_pct > 70:
                result.high_delivery = True
                result.triggers.append(
                    f"High delivery % ({result.recent_delivery_pct:.1f}%)"
                )

    # ── Insider/promoter activity ────────────────────────────────────────
    insider_trades = fetch_insider_trades(ticker)
    result.insider_trades = insider_trades

    promoter_buys = [t for t in insider_trades
                     if t.trade_type == "BUY"
                     and ("PROMOTER" in t.category.upper() or "DIRECTOR" in t.category.upper())]
    if promoter_buys:
        result.promoter_buying = True
        result.triggers.append(
            f"Promoter/insider buying ({len(promoter_buys)} transactions)"
        )

    result.trigger_count = len(result.triggers)
    return result
