"""Value Trap Detector — flags stocks that look cheap but have fundamental problems.

Checks:
    1. Profit volatility (CV > 50%)
    2. Cash-profit mismatch (CFO < 70% of profit)
    3. ROCE/ROE outlier inflation
    4. Declining revenue
    5. Debt creep (borrowings growing faster than profits)
    6. Promoter holding decline
    7. Working capital deterioration (debtor days trend)
"""

import math
from dataclasses import dataclass, field
from typing import List

from shared.data_parser import (
    get_value_series, get_latest_annual, get_ratio,
    get_promoter_holding_series, get_debtor_days_series,
)
from shared.utils import growth_rate, mean, median, logger


@dataclass
class ValueTrapResult:
    flags: List[str] = field(default_factory=list)
    score: int = 0  # count of flags triggered

    @property
    def label(self):
        if self.score == 0:
            return "CLEAN"
        elif self.score <= 2:
            return "CAUTION"
        else:
            return "LIKELY TRAP"


def detect_value_traps(data):
    """Run all value trap checks. Returns ValueTrapResult."""
    checks = [
        _check_profit_volatility,
        _check_cash_profit_mismatch,
        _check_roce_roe_outlier_inflation,
        _check_declining_revenue,
        _check_debt_creep,
        _check_promoter_decline,
        _check_working_capital_deterioration,
    ]

    flags = []
    for check in checks:
        flag = check(data)
        if flag:
            flags.append(flag)

    result = ValueTrapResult(flags=flags, score=len(flags))

    ticker = data.get("ticker", "???")
    if flags:
        logger.info(f"{ticker} value trap flags ({result.label}): {'; '.join(flags)}")

    return result


def _check_profit_volatility(data):
    """Flag if net profit has high coefficient of variation (>0.50) over 5 years."""
    profits = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    if not profits or len(profits) < 3:
        return None

    clean = [p for p in profits if p is not None]
    if len(clean) < 3:
        return None

    avg = sum(clean) / len(clean)
    if avg <= 0:
        return "Avg profit negative over 5 years"

    variance = sum((p - avg) ** 2 for p in clean) / len(clean)
    std = math.sqrt(variance)
    cv = std / abs(avg)

    if cv > 0.50:
        return f"Erratic profits (CV={cv:.0%})"
    return None


def _check_cash_profit_mismatch(data):
    """Flag if cumulative operating cash flow < 70% of cumulative net profit."""
    profits = get_value_series(data, "profit_loss", "Net Profit", n_years=5)
    cfo = get_value_series(data, "cash_flow", "Cash from Operating Activity", n_years=5)

    if not profits or not cfo or len(profits) < 3 or len(cfo) < 3:
        return None

    # Use the shorter of the two series
    n = min(len(profits), len(cfo))
    profits = profits[-n:]
    cfo = cfo[-n:]

    cum_profit = sum(p for p in profits if p is not None and p > 0)
    cum_cfo = sum(c for c in cfo if c is not None)

    if cum_profit <= 0:
        return None

    ratio = cum_cfo / cum_profit
    if ratio < 0.70:
        return f"Cash flow doesn't back profits (CFO/Profit={ratio:.0%})"
    return None


def _check_roce_roe_outlier_inflation(data):
    """Flag if mean ROCE or ROE is >1.3x the median — outlier years inflate average."""
    roce_series = get_value_series(data, "ratios", "ROCE %", n_years=5)
    roe_series = get_value_series(data, "ratios", "Return on equity", n_years=5)
    if not roe_series:
        roe_series = get_value_series(data, "ratios", "ROE %", n_years=5)

    flags = []

    for name, series in [("ROCE", roce_series), ("ROE", roe_series)]:
        if not series or len(series) < 3:
            continue
        clean = [v for v in series if v is not None and v > 0]
        if len(clean) < 3:
            continue

        avg = mean(clean)
        med = median(clean)
        if med and med > 0 and avg and avg / med > 1.30:
            flags.append(f"{name} inflated by outlier years (mean={avg:.1f}% vs median={med:.1f}%)")

    return flags[0] if flags else None


def _check_declining_revenue(data):
    """Flag if 3-year sales CAGR is negative."""
    sales = get_value_series(data, "profit_loss", "Sales", n_years=3)
    if not sales or len(sales) < 2:
        return None

    g = growth_rate(sales)
    if g is not None and g < 0:
        return f"Revenue declining ({g*100:+.1f}% CAGR)"
    return None


def _check_debt_creep(data):
    """Flag if borrowings growing >15% CAGR while profit growth <5%."""
    borrowings = get_value_series(data, "balance_sheet", "Borrowings", n_years=5)
    profits = get_value_series(data, "profit_loss", "Net Profit", n_years=5)

    if not borrowings or len(borrowings) < 2:
        return None

    debt_growth = growth_rate(borrowings)
    profit_growth = growth_rate(profits) if profits and len(profits) >= 2 else None

    if debt_growth is not None and debt_growth > 0.15:
        if profit_growth is None or profit_growth < 0.05:
            pg_str = f"{profit_growth*100:+.1f}%" if profit_growth is not None else "N/A"
            return f"Debt growing faster than profits (debt +{debt_growth*100:.0f}% vs profit {pg_str})"
    return None


def _check_promoter_decline(data):
    """Flag if promoter holding has declined by >2 percentage points over available data."""
    series = get_promoter_holding_series(data)
    if not series or len(series) < 4:
        return None

    clean = [v for v in series if v is not None]
    if len(clean) < 4:
        return None

    # Compare earliest to latest
    decline = clean[0] - clean[-1]
    if decline > 2.0:
        return f"Promoter holding declining ({clean[0]:.1f}% \u2192 {clean[-1]:.1f}%, -{decline:.1f}pp)"
    return None


def _check_working_capital_deterioration(data):
    """Flag if debtor days have increased significantly (>20% over 3 years)."""
    debtors = get_debtor_days_series(data, n_years=5)
    if not debtors or len(debtors) < 3:
        return None

    clean = [d for d in debtors if d is not None and d > 0]
    if len(clean) < 3:
        return None

    early_avg = sum(clean[:2]) / 2
    recent_avg = sum(clean[-2:]) / 2

    if early_avg > 0 and recent_avg > early_avg * 1.20:
        return (f"Debtor days deteriorating ({early_avg:.0f} \u2192 {recent_avg:.0f} days, "
                f"+{((recent_avg/early_avg)-1)*100:.0f}%)")
    return None
