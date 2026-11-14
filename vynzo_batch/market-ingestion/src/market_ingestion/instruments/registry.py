"""Instrument lookups: which listings to ingest and their provider tokens.

Functions take an open connection and never commit.
"""

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class ActiveListing:
    listing_id: int
    exchange: str
    symbol: str
    provider_symbol: str


_SELECT = (
    "SELECT l.listing_id, l.exchange::text AS exchange, l.symbol, ps.provider_symbol "
    "FROM listings l JOIN provider_symbols ps "
    "ON ps.listing_id = l.listing_id AND ps.provider = %s "
)


def active_listings(conn: psycopg.Connection, provider: str = "yahoo") -> list[ActiveListing]:
    """Active listings that have a provider symbol, ordered by exchange then symbol."""
    rows = conn.execute(
        _SELECT + "WHERE l.is_active ORDER BY l.exchange::text, l.symbol", (provider,)
    ).fetchall()
    return [ActiveListing(**r) for r in rows]


def find_listing(
    conn: psycopg.Connection, exchange: str, symbol: str, provider: str = "yahoo"
) -> ActiveListing | None:
    """The listing for (exchange, symbol) if it has a provider symbol, active or not."""
    row = conn.execute(
        _SELECT + "WHERE l.exchange = %s::exchange_code AND l.symbol = %s",
        (provider, exchange, symbol),
    ).fetchone()
    return ActiveListing(**row) if row else None
