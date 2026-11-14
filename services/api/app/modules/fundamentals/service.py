"""Business use cases for fundamentals. Calls the repository; knows nothing about HTTP."""

from datetime import date, timedelta
from typing import Any

import psycopg

from app.modules.fundamentals import repository


def upcoming_events(
    conn: psycopg.Connection, *, today: date, days: int, limit: int
) -> list[dict[str, Any]]:
    return repository.list_events(conn, start=today, end=today + timedelta(days=days), limit=limit)
