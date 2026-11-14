"""Company fundamentals from Yahoo Finance: ratio snapshot, annual revenue / net income, dividends.

One row set per company: the first active listing with a Yahoo symbol supplies it (NSE sorts
before BSE). A failed lookup keeps the company's previous data; each company commits on its own.
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
import psycopg

log = logging.getLogger(__name__)

# Our column <- Yahoo Ticker.info key.
SNAPSHOT_FIELDS = {
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_book": "priceToBook",
    "revenue_ttm": "totalRevenue",
    "revenue_growth": "revenueGrowth",
    "net_income_ttm": "netIncomeToCommon",
    "profit_margin": "profitMargins",
    "return_on_equity": "returnOnEquity",
    "total_debt": "totalDebt",
    "total_cash": "totalCash",
    "debt_to_equity": "debtToEquity",
    "current_ratio": "currentRatio",
    "free_cash_flow": "freeCashflow",
    "insider_pct": "heldPercentInsiders",
    "institutional_pct": "heldPercentInstitutions",
}
REVENUE_ROWS = ("Total Revenue", "Operating Revenue")
NET_INCOME_ROWS = ("Net Income", "Net Income Common Stockholders")
DEBT_ROWS = ("Total Debt",)
DIVIDEND_YEARS = 3  # history kept per run; the API needs only the last 12 months

_COMPANIES = """
SELECT DISTINCT ON (l.company_id) l.company_id, ps.provider_symbol
FROM listings l JOIN provider_symbols ps ON ps.listing_id = l.listing_id AND ps.provider = 'yahoo'
WHERE l.is_active AND l.kind = 'equity' AND l.company_id IS NOT NULL
ORDER BY l.company_id, l.exchange::text DESC
"""
_UPSERT_SNAPSHOT = f"""
INSERT INTO company_fundamentals (company_id, as_of, {", ".join(SNAPSHOT_FIELDS)})
VALUES (%(company_id)s, %(as_of)s, {", ".join(f"%({k})s" for k in SNAPSHOT_FIELDS)})
ON CONFLICT (company_id, as_of) DO UPDATE SET
    {", ".join(f"{k} = EXCLUDED.{k}" for k in SNAPSHOT_FIELDS)}, updated_at = now()
"""  # noqa: S608 - fixed column list
_UPSERT_ANNUAL = """
INSERT INTO company_annual_financials (company_id, fiscal_year_end, revenue, net_income, total_debt)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (company_id, fiscal_year_end) DO UPDATE SET
    revenue = EXCLUDED.revenue, net_income = EXCLUDED.net_income, total_debt = EXCLUDED.total_debt
"""
_UPSERT_DIVIDEND = """
INSERT INTO company_dividend (company_id, ex_date, amount) VALUES (%s, %s, %s)
ON CONFLICT (company_id, ex_date) DO UPDATE SET amount = EXCLUDED.amount
"""


@dataclass
class YahooFundamentals:
    info: dict[str, Any]
    income_stmt: pd.DataFrame
    dividends: pd.Series
    balance_sheet: pd.DataFrame | None = None


@dataclass
class FundamentalsReport:
    as_of: str
    companies: int = 0
    updated: int = 0
    failed: list[str] = field(default_factory=list)


def _default_fetch(provider_symbol: str) -> YahooFundamentals:
    import yfinance as yf

    t = yf.Ticker(provider_symbol)
    return YahooFundamentals(t.info or {}, t.income_stmt, t.dividends, t.balance_sheet)


def _number(value: Any) -> float | None:
    """A finite float, or None for missing, NaN, infinite and non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def parse_snapshot(info: dict[str, Any]) -> dict[str, float | None]:
    out = {ours: _number(info.get(theirs)) for ours, theirs in SNAPSHOT_FIELDS.items()}
    if out["debt_to_equity"] is not None:
        out["debt_to_equity"] /= 100  # Yahoo reports it as a percentage (32.4 = 0.324)
    return out


def _row(df: pd.DataFrame, names: tuple[str, ...]) -> pd.Series | None:
    return next((df.loc[n] for n in names if n in df.index), None)


def _by_year(df: pd.DataFrame | None, names: tuple[str, ...]) -> dict[date, float]:
    row = _row(df, names) if df is not None and not df.empty else None
    if row is None:
        return {}
    values = {pd.Timestamp(col).date(): _number(v) for col, v in row.items()}
    return {day: v for day, v in values.items() if v is not None}


def parse_annual(
    income_stmt: pd.DataFrame | None, balance_sheet: pd.DataFrame | None = None
) -> list[tuple[date, float | None, float | None, float | None]]:
    """(fiscal year end, revenue, net income, total debt) per fiscal year, oldest first."""
    revenue = _by_year(income_stmt, REVENUE_ROWS)
    income = _by_year(income_stmt, NET_INCOME_ROWS)
    debt = _by_year(balance_sheet, DEBT_ROWS)
    years = sorted(set(revenue) | set(income) | set(debt))
    return [(y, revenue.get(y), income.get(y), debt.get(y)) for y in years]


def parse_dividends(dividends: pd.Series | None, today: date) -> list[tuple[date, float]]:
    """(ex-date, amount per share) for the last DIVIDEND_YEARS years; zero or junk dropped."""
    if dividends is None or dividends.empty:
        return []
    cutoff = date(today.year - DIVIDEND_YEARS, today.month, min(today.day, 28))
    out = []
    for ts, amount in dividends.items():
        day, value = pd.Timestamp(ts).date(), _number(amount)
        if day >= cutoff and value is not None and value > 0:
            out.append((day, value))
    return out


def sync_fundamentals(
    conn: psycopg.Connection,
    today: date,
    fetch: Callable[[str], YahooFundamentals] | None = None,
) -> FundamentalsReport:
    fetch = fetch or _default_fetch
    report = FundamentalsReport(as_of=today.isoformat())
    for row in conn.execute(_COMPANIES).fetchall():
        company_id, symbol = row["company_id"], row["provider_symbol"]
        report.companies += 1
        try:
            data = fetch(symbol)
            snapshot = parse_snapshot(data.info)
            annual = parse_annual(data.income_stmt, data.balance_sheet)
            dividends = parse_dividends(data.dividends, today)
        except Exception:  # one bad ticker must not stop the run
            log.exception("fundamentals lookup failed for %s", symbol)
            report.failed.append(symbol)
            continue
        if not any(v is not None for v in snapshot.values()) and not annual:
            report.failed.append(symbol)
            continue
        with conn.cursor() as cur:
            cur.execute(_UPSERT_SNAPSHOT, {"company_id": company_id, "as_of": today, **snapshot})
            cur.executemany(_UPSERT_ANNUAL, [(company_id, *a) for a in annual])
            cur.executemany(_UPSERT_DIVIDEND, [(company_id, *d) for d in dividends])
        conn.commit()
        report.updated += 1
    return report
