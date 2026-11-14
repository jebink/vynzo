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


def _like_patterns(q: str) -> tuple[str, str]:
    """(prefix, substring) ILIKE patterns for `q`, with LIKE wildcards escaped (ESCAPE '\\')."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%", f"%{escaped}%"


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
        params["prefix"], params["substr"] = _like_patterns(q)
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


# ---- Ingestion selection ----
# A "selection row" is one symbol with its NSE and BSE listings side by side. `is_active` on a
# listing is what the daily pipeline (ingestion, indicators, signals) runs over.

_SELECTION_GROUPED = """
    WITH grouped AS (
        SELECT l.symbol,
               max(c.name) AS company_name,
               max(c.isin) AS isin,
               min(l.kind) AS kind,
               bool_or(l.is_active) AS any_active,
               max(l.listing_id) FILTER (WHERE l.exchange = 'NSE') AS nse_listing_id,
               bool_or(l.is_active) FILTER (WHERE l.exchange = 'NSE') AS nse_is_active,
               max(p.provider_symbol) FILTER (WHERE l.exchange = 'NSE') AS nse_provider_symbol,
               max(l.listing_id) FILTER (WHERE l.exchange = 'BSE') AS bse_listing_id,
               bool_or(l.is_active) FILTER (WHERE l.exchange = 'BSE') AS bse_is_active,
               max(p.provider_symbol) FILTER (WHERE l.exchange = 'BSE') AS bse_provider_symbol
        FROM listings l
        LEFT JOIN companies c USING (company_id)
        LEFT JOIN provider_symbols p ON p.listing_id = l.listing_id AND p.provider = %(provider)s
        {symbol_filter}
        GROUP BY l.symbol
    )
"""

_STATUS_FILTERS = {"all": "TRUE", "selected": "any_active", "unselected": "NOT any_active"}


def search_selection(
    conn: psycopg.Connection,
    *,
    q: str | None,
    status: str,
    offset: int,
    limit: int,
    provider: str,
) -> tuple[int, list[dict[str, Any]]]:
    """(total matching, one page of selection rows ordered by symbol)."""
    params: dict[str, Any] = {"provider": provider, "offset": offset, "limit": limit}
    where = [_STATUS_FILTERS[status]]
    if q:
        where.append(
            "(symbol ILIKE %(prefix)s ESCAPE '\\' OR company_name ILIKE %(substr)s ESCAPE '\\')"
        )
        params["prefix"], params["substr"] = _like_patterns(q)
    grouped = _SELECTION_GROUPED.format(symbol_filter="")
    condition = " AND ".join(where)
    with conn.cursor(row_factory=dict_row) as cur:
        total = cur.execute(
            f"{grouped} SELECT count(*) AS n FROM grouped WHERE {condition}",  # noqa: S608
            params,
        ).fetchone()["n"]
        rows = cur.execute(
            f"{grouped} SELECT * FROM grouped WHERE {condition} "  # noqa: S608
            "ORDER BY symbol OFFSET %(offset)s LIMIT %(limit)s",
            params,
        ).fetchall()
    return total, rows


def selection_row(conn: psycopg.Connection, symbol: str, provider: str) -> dict[str, Any] | None:
    grouped = _SELECTION_GROUPED.format(symbol_filter="WHERE l.symbol = %(symbol)s")
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"{grouped} SELECT * FROM grouped",  # noqa: S608 - fixed fragments only
            {"provider": provider, "symbol": symbol},
        ).fetchone()


def selected_counts(conn: psycopg.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT exchange::text, count(*) FROM listings WHERE is_active GROUP BY 1"
    ).fetchall()
    return dict(rows)


def last_bar_times(conn: psycopg.Connection, listing_ids: list[int]) -> dict[int, Any]:
    """Newest ohlcv_1d ts per listing, via the (listing_id, ts DESC) index; absent if none."""
    if not listing_ids:
        return {}
    rows = conn.execute(
        "SELECT x.id, (SELECT b.ts FROM ohlcv_1d b WHERE b.listing_id = x.id "
        "              ORDER BY b.ts DESC LIMIT 1) "
        "FROM unnest(%s::bigint[]) AS x(id)",
        (listing_ids,),
    ).fetchall()
    return {listing_id: ts for listing_id, ts in rows if ts is not None}


def symbol_listings(conn: psycopg.Connection, symbol: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT listing_id, exchange::text AS exchange, kind, company_id, is_active "
            "FROM listings WHERE symbol = %s",
            (symbol,),
        ).fetchall()


def set_active(conn: psycopg.Connection, listing_id: int, active: bool) -> None:
    conn.execute("UPDATE listings SET is_active = %s WHERE listing_id = %s", (active, listing_id))


def create_listing(
    conn: psycopg.Connection, *, exchange: str, symbol: str, kind: str, company_id: int
) -> int:
    row = conn.execute(
        "INSERT INTO listings (exchange, symbol, kind, company_id, is_active) "
        "VALUES (%s, %s, %s, %s, false) RETURNING listing_id",
        (exchange, symbol, kind, company_id),
    ).fetchone()
    return row[0]


def ensure_provider_symbol(
    conn: psycopg.Connection, *, provider: str, provider_symbol: str, listing_id: int
) -> None:
    """Add the listing's provider symbol unless it already has one for this provider."""
    conn.execute(
        "INSERT INTO provider_symbols (provider, provider_symbol, listing_id) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (provider, provider_symbol, listing_id),
    )
