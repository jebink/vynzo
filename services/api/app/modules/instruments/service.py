"""Business use cases for instruments. Calls the repository; knows nothing about HTTP."""

from typing import Any

import psycopg

from app.modules.instruments import repository


class ListingNotFound(Exception):
    """Raised when an exchange/symbol pair has no listing."""


def search(
    conn: psycopg.Connection, *, q: str | None, exchange: str | None, active: bool, limit: int
) -> list[dict[str, Any]]:
    return repository.search_listings(conn, q=q, exchange=exchange, active=active, limit=limit)


def require_listing(conn: psycopg.Connection, exchange: str, symbol: str) -> dict[str, Any]:
    listing = repository.get_listing(conn, exchange, symbol)
    if listing is None:
        raise ListingNotFound
    return listing


def listing_detail(conn: psycopg.Connection, exchange: str, symbol: str) -> dict[str, Any]:
    listing = require_listing(conn, exchange, symbol)
    bars = repository.latest_two_bars(conn, listing["listing_id"])
    return {
        **listing,
        "latest": bars[0] if bars else None,
        "previous_close": bars[1]["close"] if len(bars) > 1 else None,
    }
