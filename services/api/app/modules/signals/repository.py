"""Persistence for signals: SQL against PostgreSQL/TimescaleDB. Schema lives in
database/postgres.
"""

from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row


def _run(conn: psycopg.Connection, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, params).fetchall()


def _filters(conditions: list[str]) -> str:
    return f"WHERE {' AND '.join(conditions)} " if conditions else ""


def list_types(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return _run(
        conn,
        "SELECT signal_type, count(*)::int AS count, max(as_of) AS latest_as_of "
        "FROM signal GROUP BY signal_type ORDER BY signal_type",
        {},
    )


def list_signals(
    conn: psycopg.Connection,
    *,
    signal_type: str | None,
    exchange: str | None,
    symbol: str | None,
    since: date | None,
    limit: int,
) -> list[dict[str, Any]]:
    cond: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if signal_type:
        cond.append("s.signal_type = %(signal_type)s")
        params["signal_type"] = signal_type
    if exchange:
        cond.append("l.exchange = %(exchange)s")
        params["exchange"] = exchange.upper()
    if symbol:
        cond.append("l.symbol = %(symbol)s")
        params["symbol"] = symbol
    if since:
        cond.append("s.as_of >= %(since)s")
        params["since"] = f"{since}T00:00:00+00:00"
    query = (
        "SELECT s.id, s.listing_id, l.exchange::text AS exchange, l.symbol, "  # noqa: S608
        "c.name AS company_name, s.signal_type, s.as_of, s.strength, s.price, s.volume, "
        "s.avg_volume, s.rationale, s.meta, s.calc_version "
        "FROM signal s JOIN listings l USING (listing_id) "
        "LEFT JOIN companies c USING (company_id) "
        + _filters(cond)
        + "ORDER BY s.as_of DESC, s.strength DESC NULLS LAST, s.id DESC LIMIT %(limit)s"
    )
    return _run(conn, query, params)


def list_swing(
    conn: psycopg.Connection, *, exchange: str | None, symbol: str | None, limit: int
) -> list[dict[str, Any]]:
    cond: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if exchange:
        cond.append("l.exchange = %(exchange)s")
        params["exchange"] = exchange.upper()
    if symbol:
        cond.append("l.symbol = %(symbol)s")
        params["symbol"] = symbol
    query = (
        "SELECT w.id, w.listing_id, l.exchange::text AS exchange, l.symbol, w.as_of, "  # noqa: S608
        "w.signal, w.entry, w.stop_loss, w.target_1, w.target_2, w.risk_reward, "
        "w.rationale, w.calc_version "
        "FROM swing_signals w JOIN listings l USING (listing_id) "
        + _filters(cond)
        + "ORDER BY w.as_of DESC, w.id DESC LIMIT %(limit)s"
    )
    return _run(conn, query, params)
