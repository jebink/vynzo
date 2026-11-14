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
