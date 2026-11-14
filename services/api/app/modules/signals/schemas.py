"""Pydantic request/response models for signals (the public API contract)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SignalType(BaseModel):
    signal_type: str
    count: int
    latest_as_of: datetime


class Signal(BaseModel):
    id: int
    listing_id: int
    exchange: str
    symbol: str
    company_name: str | None
    signal_type: str
    as_of: datetime
    strength: float | None
    price: float | None
    volume: int | None
    avg_volume: float | None
    rationale: str | None
    meta: dict[str, Any]
    calc_version: str


class SwingSignal(BaseModel):
    id: int
    listing_id: int
    exchange: str
    symbol: str
    as_of: datetime
    signal: str
    entry: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    risk_reward: float | None
    rationale: str | None
    calc_version: str
