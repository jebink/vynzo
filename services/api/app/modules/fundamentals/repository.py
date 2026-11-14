"""Persistence for fundamentals: SQL against PostgreSQL/TimescaleDB. Schema lives in
database/postgres.
"""

from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row


def list_events(
    conn: psycopg.Connection, *, start: date, end: date, limit: int
) -> list[dict[str, Any]]:
    query = """
        SELECT l.exchange::text AS exchange, l.symbol, c.name AS company_name,
               e.event_type, e.event_date, e.details, e.source
        FROM corporate_event e
        JOIN listings l USING (listing_id)
        LEFT JOIN companies c USING (company_id)
        WHERE e.event_date BETWEEN %(start)s AND %(end)s AND l.is_active
        ORDER BY e.event_date, e.event_type, l.symbol
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, {"start": start, "end": end, "limit": limit}).fetchall()


# ---- Company overview (stock page) ----


def company_for(conn: psycopg.Connection, exchange: str, symbol: str) -> dict[str, Any] | None:
    """The listing's company with its profile and latest close."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT l.listing_id, l.exchange::text AS exchange, l.symbol, l.company_id, "
            "c.name AS company_name, c.sector, c.industry, c.shares_outstanding, "
            "o.close, o.ts AS close_ts "
            "FROM listings l LEFT JOIN companies c USING (company_id) "
            "LEFT JOIN ohlcv_latest o ON o.listing_id = l.listing_id "
            "WHERE l.exchange = %s AND l.symbol = %s",
            (exchange, symbol),
        ).fetchone()


def latest_fundamentals(conn: psycopg.Connection, company_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT * FROM company_fundamentals WHERE company_id = %s ORDER BY as_of DESC LIMIT 1",
            (company_id,),
        ).fetchone()


def peer_pes(conn: psycopg.Connection, column: str, value: str) -> list[float]:
    """Latest positive trailing P/E of every company with the same industry (or sector)."""
    assert column in ("industry", "sector")
    with conn.cursor() as cur:
        rows = cur.execute(
            "SELECT f.trailing_pe FROM companies c "  # noqa: S608 - column is whitelisted
            "JOIN LATERAL (SELECT trailing_pe FROM company_fundamentals x "
            "  WHERE x.company_id = c.company_id ORDER BY as_of DESC LIMIT 1) f ON true "
            f"WHERE c.{column} = %s AND f.trailing_pe > 0",
            (value,),
        ).fetchall()
    return [r[0] for r in rows]


def annual_financials(conn: psycopg.Connection, company_id: int, years: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT fiscal_year_end, revenue, net_income, total_debt "
            "FROM company_annual_financials "
            "WHERE company_id = %s ORDER BY fiscal_year_end DESC LIMIT %s",
            (company_id, years),
        ).fetchall()
    return list(reversed(rows))


def dividends_since(conn: psycopg.Connection, company_id: int, since: date) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT ex_date, amount FROM company_dividend WHERE company_id = %s AND ex_date >= %s "
            "ORDER BY ex_date DESC",
            (company_id, since),
        ).fetchall()


def orders_since(conn: psycopg.Connection, company_id: int, since: date, limit: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT reported_on, counterparty, description, value_inr, source_url, headline "
            "FROM company_order WHERE company_id = %s AND reported_on >= %s "
            "ORDER BY reported_on DESC, id DESC LIMIT %s",
            (company_id, since, limit),
        ).fetchall()
