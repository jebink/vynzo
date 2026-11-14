"""Pydantic request/response models for instruments (the public API contract)."""

from datetime import datetime

from pydantic import BaseModel


class Listing(BaseModel):
    listing_id: int
    exchange: str
    symbol: str
    kind: str
    company_name: str | None
    isin: str | None
    is_active: bool


class LatestBar(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class ListingDetail(Listing):
    latest: LatestBar | None
    previous_close: float | None


# ---- Ingestion selection ----


class ListingState(BaseModel):
    """One exchange listing of a symbol as the daily pipeline sees it."""

    listing_id: int
    is_active: bool
    provider_symbol: str | None
    last_bar: datetime | None


class SelectionRow(BaseModel):
    symbol: str
    company_name: str | None
    isin: str | None
    kind: str
    nse: ListingState | None
    bse: ListingState | None


class SelectedCounts(BaseModel):
    NSE: int
    BSE: int


class SelectionPage(BaseModel):
    total: int
    selected: SelectedCounts
    rows: list[SelectionRow]


class SelectionUpdate(BaseModel):
    selected: bool
