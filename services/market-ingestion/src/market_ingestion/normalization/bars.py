"""Normalize raw provider records into typed bars."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from market_ingestion.providers.base import RawRecord

_FIELDS = ("Open", "High", "Low", "Close", "Volume")


@dataclass(frozen=True)
class Bar:
    listing_id: int
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def _valid(v: object) -> bool:
    if v is None:
        return False
    try:
        return not math.isnan(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def normalize(records: Iterable[RawRecord], listing_id: int) -> list[Bar]:
    """Convert records to Bars, skipping any with a NaN or missing O/H/L/C/V."""
    bars: list[Bar] = []
    for r in records:
        p = r.payload
        if not all(_valid(p.get(f)) for f in _FIELDS):
            continue
        bars.append(
            Bar(
                listing_id=listing_id,
                ts=r.bar_ts,
                open=float(p["Open"]),
                high=float(p["High"]),
                low=float(p["Low"]),
                close=float(p["Close"]),
                volume=int(p["Volume"]),
            )
        )
    return bars
