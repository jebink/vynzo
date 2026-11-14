"""Checkpointing: where each listing's data ends, and the ingest-run audit rows.

Every function takes an open connection and does NOT commit; the caller owns the transaction.
"""

from datetime import date, datetime, timedelta

import psycopg
from psycopg import sql

from market_ingestion.timeframes import TIMEFRAMES


def last_bar_ts(conn: psycopg.Connection, listing_id: int, timeframe: str) -> datetime | None:
    """Timestamp of the newest stored bar for the listing, or None if it has none."""
    query = sql.SQL("SELECT max(ts) AS ts FROM {} WHERE listing_id = %s").format(
        sql.Identifier(TIMEFRAMES[timeframe].table)
    )
    row = conn.execute(query, (listing_id,)).fetchone()
    return row["ts"] if row else None


def fetch_start(timeframe: str, last_ts: datetime | None) -> date | None:
    """First date to fetch: None (full history) without a checkpoint, else last bar minus overlap.

    1mo snaps to day 1 of the month after the overlap is subtracted (as vinzo-core does).
    """
    if last_ts is None:
        return None
    overlap = TIMEFRAMES[timeframe].overlap or timedelta(0)
    start = last_ts.date() - overlap
    if timeframe == "1mo":
        start = start.replace(day=1)
    return start


def start_run(conn: psycopg.Connection, listing_id: int, provider: str, timeframe: str) -> int:
    """Open an ingest_runs row with status 'running' and return its id."""
    row = conn.execute(
        "INSERT INTO ingest_runs (listing_id, provider, timeframe) VALUES (%s, %s, %s) "
        "RETURNING id",
        (listing_id, provider, timeframe),
    ).fetchone()
    assert row is not None
    return row["id"]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    *,
    rows: int,
    gaps: int,
    status: str,
    notes: str | None = None,
) -> None:
    """Close the run: set counts, status, notes and finished_at."""
    conn.execute(
        "UPDATE ingest_runs SET finished_at = now(), rows_upserted = %s, gaps_found = %s, "
        "status = %s, notes = %s WHERE id = %s",
        (rows, gaps, status, notes, run_id),
    )
