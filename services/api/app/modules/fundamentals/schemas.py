"""Pydantic request/response models for fundamentals (the public API contract)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel


class CorporateEvent(BaseModel):
    exchange: str
    symbol: str
    company_name: str | None
    event_type: Literal["results", "ex_dividend"]
    event_date: date
    details: dict[str, Any]
    source: str


# ---- Company overview (stock page) ----


class Metrics(BaseModel):
    """Yahoo Finance snapshot. Fractions for growth, margins, ROE; INR for amounts."""

    trailing_pe: float | None
    forward_pe: float | None
    price_to_book: float | None
    revenue_ttm: float | None
    revenue_growth: float | None
    net_income_ttm: float | None
    profit_margin: float | None
    return_on_equity: float | None
    total_debt: float | None
    total_cash: float | None
    debt_to_equity: float | None
    current_ratio: float | None
    free_cash_flow: float | None


class IndustryPE(BaseModel):
    median: float | None
    peers: int
    basis: Literal["industry", "sector"] | None
    group: str | None


class Ownership(BaseModel):
    insider_pct: float | None  # promoters and insiders, fraction
    institutional_pct: float | None


class DividendPayout(BaseModel):
    ex_date: date
    amount: float


class Dividends(BaseModel):
    ttm_per_share: float | None
    yield_pct: float | None
    payouts: list[DividendPayout]


class AnnualFigure(BaseModel):
    fiscal_year_end: date
    revenue: float | None
    net_income: float | None
    total_debt: float | None


class DebtCleared(BaseModel):
    """Debt paid down from the highest fiscal-year-end debt to the latest one (negative = rose)."""

    peak: float
    peak_year_end: date
    latest: float
    latest_year_end: date
    cleared: float
    cleared_pct: float  # of the peak, %


class CompanyOrder(BaseModel):
    reported_on: date
    counterparty: str | None
    description: str
    value_inr: float | None
    source_url: str
    headline: str


class CompanyOverview(BaseModel):
    exchange: str
    symbol: str
    company_name: str | None
    sector: str | None
    industry: str | None
    price: float | None
    price_as_of: datetime | None
    market_cap: float | None
    fundamentals_as_of: date | None
    metrics: Metrics
    industry_pe: IndustryPE
    ownership: Ownership
    dividends: Dividends
    annual: list[AnnualFigure]
    debt_cleared: DebtCleared | None
    orders: list[CompanyOrder]
