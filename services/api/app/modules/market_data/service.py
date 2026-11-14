"""Business use cases for market_data. Calls the repository; knows nothing about HTTP."""

from datetime import date
from typing import Any

import psycopg

from app.modules.instruments.service import require_listing
from app.modules.market_data import repository


def _header(listing: dict[str, Any]) -> dict[str, Any]:
    return {k: listing[k] for k in ("listing_id", "exchange", "symbol")}


def get_bars(
    conn: psycopg.Connection,
    exchange: str,
    symbol: str,
    *,
    timeframe: str,
    limit: int,
    end: date | None,
) -> dict[str, Any]:
    listing = require_listing(conn, exchange, symbol)
    bars = repository.fetch_bars(conn, timeframe, listing["listing_id"], limit, end)
    return {**_header(listing), "timeframe": timeframe, "bars": bars}


def get_indicators(
    conn: psycopg.Connection, exchange: str, symbol: str, *, limit: int, end: date | None
) -> dict[str, Any]:
    listing = require_listing(conn, exchange, symbol)
    rows = repository.fetch_indicators(conn, listing["listing_id"], limit, end)
    return {**_header(listing), "rows": rows}


def _lookback_days(points: int) -> int:
    """Calendar days that hold `points` NSE/BSE sessions (~5 per 7 days, plus holidays)."""
    return points * 2 + 14


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    closes = [float(c) for c in row["closes"]]
    close = closes[-1] if closes else None
    previous = closes[-2] if len(closes) > 1 else None
    change_pct = (close - previous) / previous * 100 if close is not None and previous else None
    return {
        **row,
        "closes": closes,
        "close": close,
        "previous_close": previous,
        "change_pct": change_pct,
    }


def get_overview(conn: psycopg.Connection, *, exchange: str | None, points: int) -> dict[str, Any]:
    rows = repository.fetch_overview(
        conn, exchange=exchange, points=points, lookback_days=_lookback_days(points)
    )
    stocks = [_snapshot(row) for row in rows]
    latest = [s["latest_ts"] for s in stocks if s["latest_ts"] is not None]
    return {"as_of": max(latest, default=None), "points": points, "stocks": stocks}
