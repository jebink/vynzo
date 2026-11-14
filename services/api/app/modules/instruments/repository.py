"""Persistence for instruments: SQL against PostgreSQL/TimescaleDB. Schema lives in
database/postgres.
"""

from typing import Any

import psycopg
from psycopg.rows import dict_row

_LISTING_COLUMNS = """
    l.listing_id, l.exchange::text AS exchange, l.symbol, l.kind,
    c.name AS company_name, c.isin, l.is_active
"""


def search_listings(
    conn: psycopg.Connection,
    *,
    q: str | None,
    exchange: str | None,
    active: bool,
    limit: int,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if q:
        where.append(
            "(l.symbol ILIKE %(prefix)s ESCAPE '\\' OR c.name ILIKE %(substr)s ESCAPE '\\')"
        )
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["prefix"] = f"{escaped}%"
        params["substr"] = f"%{escaped}%"
        params["exact"] = q.upper()
    if exchange:
        where.append("l.exchange = %(exchange)s")
        params["exchange"] = exchange.upper()
    if active:
        where.append("l.is_active")
    order = "(l.symbol = %(exact)s) DESC, " if q else ""
    query = (
        f"SELECT {_LISTING_COLUMNS} FROM listings l "  # noqa: S608 - fixed fragments only
        "LEFT JOIN companies c USING (company_id) "
        + (f"WHERE {' AND '.join(where)} " if where else "")
        + f"ORDER BY {order}l.symbol, l.exchange LIMIT %(limit)s"
    )
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, params).fetchall()


def get_listing(conn: psycopg.Connection, exchange: str, symbol: str) -> dict[str, Any] | None:
    query = (
        f"SELECT {_LISTING_COLUMNS} FROM listings l "  # noqa: S608 - fixed fragment
        "LEFT JOIN companies c USING (company_id) "
        "WHERE l.exchange = %s AND l.symbol = %s"
    )
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, (exchange.upper(), symbol)).fetchone()


def latest_two_bars(conn: psycopg.Connection, listing_id: int) -> list[dict[str, Any]]:
    """Newest two ohlcv_1d bars, newest first, via the (listing_id, ts DESC) index."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv_1d "
            "WHERE listing_id = %s ORDER BY ts DESC LIMIT 2",
            (listing_id,),
        ).fetchall()
