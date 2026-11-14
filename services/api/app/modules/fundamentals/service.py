"""Business use cases for fundamentals. Calls the repository; knows nothing about HTTP."""

import statistics
from datetime import date, timedelta
from typing import Any

import psycopg

from app.modules.fundamentals import repository


def upcoming_events(
    conn: psycopg.Connection, *, today: date, days: int, limit: int
) -> list[dict[str, Any]]:
    return repository.list_events(conn, start=today, end=today + timedelta(days=days), limit=limit)


# ---- Company overview (stock page) ----

MIN_PEERS = 3
TREND_YEARS = 4
ORDERS_SHOWN = 20
METRICS = (
    "trailing_pe", "forward_pe", "price_to_book", "revenue_ttm", "revenue_growth",
    "net_income_ttm", "profit_margin", "return_on_equity", "total_debt", "total_cash",
    "debt_to_equity", "current_ratio", "free_cash_flow",
)  # fmt: skip


class CompanyNotFound(Exception):
    """No listing with this exchange and symbol."""


def industry_pe(conn: psycopg.Connection, industry: str | None, sector: str | None) -> dict:
    """Median peer P/E: same industry if it has MIN_PEERS companies, else same sector."""
    for basis, value in (("industry", industry), ("sector", sector)):
        if value:
            pes = repository.peer_pes(conn, basis, value)
            if len(pes) >= MIN_PEERS:
                return {
                    "median": statistics.median(pes),
                    "peers": len(pes),
                    "basis": basis,
                    "group": value,
                }
    return {"median": None, "peers": 0, "basis": None, "group": industry or sector}


def ttm_dividends(rows: list[dict[str, Any]]) -> float | None:
    total = sum(float(r["amount"]) for r in rows)
    return total if rows else None


def debt_cleared(annual: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Peak fiscal-year-end debt minus the latest one, on the same balance-sheet basis."""
    years = [
        (a["fiscal_year_end"], float(a["total_debt"]))
        for a in annual
        if a.get("total_debt") is not None
    ]
    if len(years) < 2:
        return None
    latest_year, latest = max(years)
    peak_year, peak = max(years, key=lambda y: (y[1], y[0]))
    if peak <= 0:
        return None
    return {
        "peak": peak,
        "peak_year_end": peak_year,
        "latest": latest,
        "latest_year_end": latest_year,
        "cleared": peak - latest,
        "cleared_pct": (peak - latest) / peak * 100,
    }


def company_overview(conn: psycopg.Connection, exchange: str, symbol: str, today: date) -> dict:
    company = repository.company_for(conn, exchange, symbol)
    if company is None:
        raise CompanyNotFound
    close = float(company["close"]) if company["close"] is not None else None
    shares = company["shares_outstanding"]
    cid = company["company_id"]
    snap = repository.latest_fundamentals(conn, cid) if cid else None
    year_ago = today - timedelta(days=365)
    dividends = repository.dividends_since(conn, cid, year_ago) if cid else []
    ttm = ttm_dividends(dividends)
    annual = repository.annual_financials(conn, cid, TREND_YEARS) if cid else []
    return {
        "exchange": company["exchange"],
        "symbol": company["symbol"],
        "company_name": company["company_name"],
        "sector": company["sector"],
        "industry": company["industry"],
        "price": close,
        "price_as_of": company["close_ts"],
        "market_cap": shares * close if shares and close else None,
        "fundamentals_as_of": snap["as_of"] if snap else None,
        "metrics": {k: snap[k] if snap else None for k in METRICS},
        "industry_pe": industry_pe(conn, company["industry"], company["sector"]),
        "ownership": {
            "insider_pct": snap["insider_pct"] if snap else None,
            "institutional_pct": snap["institutional_pct"] if snap else None,
        },
        "dividends": {
            "ttm_per_share": ttm,
            "yield_pct": ttm / close * 100 if ttm and close else None,
            "payouts": dividends,
        },
        "annual": annual,
        "debt_cleared": debt_cleared(annual),
        "orders": repository.orders_since(conn, cid, year_ago, ORDERS_SHOWN) if cid else [],
    }
