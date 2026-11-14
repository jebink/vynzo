"""Pydantic request/response models for fundamentals (the public API contract)."""

from datetime import date
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
