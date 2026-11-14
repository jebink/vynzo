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
