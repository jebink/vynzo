"""Pydantic response models for the focus module (the public API contract)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class FocusPart(BaseModel):
    points: float
    max: float
    reason: str


class FocusHeadline(BaseModel):
    title: str
    url: str
    source: str
    publisher: str | None = None
    published: datetime | None = None


class FocusNews(BaseModel):
    label: str | None
    sentiment: float | None
    confidence: float | None
    summary: str | None
    headline_count: int
    headlines: list[FocusHeadline]


class FocusPerformance(BaseModel):
    close: float | None
    change_1d_pct: float | None
    change_5d_pct: float | None
    change_20d_pct: float | None
    move_sigma: float | None
    rvol: float | None


class FocusEvent(BaseModel):
    type: str
    date: date
    days_away: int
    details: dict


class FocusStock(BaseModel):
    listing_id: int
    exchange: str
    symbol: str
    company_name: str | None
    sector: str | None
    score: int
    grade: Literal["A", "B", "C", "D"]
    parts: dict[Literal["news", "market", "event"], FocusPart]
    news: FocusNews | None
    performance: FocusPerformance
    event: FocusEvent | None


class FocusResponse(BaseModel):
    as_of: datetime | None
    stock: FocusStock | None
