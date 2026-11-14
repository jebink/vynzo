"""Business use cases for signals. Calls the repository; knows nothing about HTTP."""

from datetime import date
from typing import Any

import psycopg

from app.modules.signals import repository


def signal_types(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return repository.list_types(conn)


def signals(
    conn: psycopg.Connection,
    *,
    signal_type: str | None,
    exchange: str | None,
    symbol: str | None,
    since: date | None,
    limit: int,
) -> list[dict[str, Any]]:
    return repository.list_signals(
        conn, signal_type=signal_type, exchange=exchange, symbol=symbol, since=since, limit=limit
    )


def swing(
    conn: psycopg.Connection, *, exchange: str | None, symbol: str | None, limit: int
) -> list[dict[str, Any]]:
    return repository.list_swing(conn, exchange=exchange, symbol=symbol, limit=limit)
