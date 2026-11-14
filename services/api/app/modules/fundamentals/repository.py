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
