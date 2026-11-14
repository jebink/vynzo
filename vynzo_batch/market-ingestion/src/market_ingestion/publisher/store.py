"""Write path for bars, raw provider records and gaps.

Every function takes an open connection and does NOT commit; the caller owns the transaction.
"""

import json
import math
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from market_ingestion.normalization.bars import Bar
from market_ingestion.providers.base import RawRecord
from market_ingestion.timeframes import TIMEFRAMES


def _clean(value: Any) -> Any:
    """Replace non-finite floats (NaN, inf) with None; they are not valid JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def _default(obj: Any) -> Any:
    item = getattr(obj, "item", None)  # numpy scalars
    if callable(item):
        return _clean(item())
    return str(obj)


def _dumps(obj: Any) -> str:
    return json.dumps(_clean(obj), allow_nan=False, default=_default)


def upsert_bars(conn: psycopg.Connection, timeframe: str, bars: list[Bar]) -> int:
    """Upsert bars into the timeframe's table (ON CONFLICT (listing_id, ts) DO UPDATE).

    Returns the number of input bars written. Does not commit.
    """
    if not bars:
        return 0
    table = TIMEFRAMES[timeframe].table
    query = sql.SQL(
        "INSERT INTO {} (listing_id, ts, open, high, low, close, volume) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (listing_id, ts) DO UPDATE SET "
        "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, "
        "close = EXCLUDED.close, volume = EXCLUDED.volume"
    ).format(sql.Identifier(table))
    with conn.cursor() as cur:
        cur.executemany(
            query,
            [(b.listing_id, b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars],
        )
    return len(bars)


def insert_raw(conn: psycopg.Connection, run_id: int, records: list[RawRecord]) -> int:
    """Append raw records to raw_eod_bars (never updated). NaN is stored as null.

    Returns the number of rows inserted. Does not commit.
    """
    if not records:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw_eod_bars "
            "(ingest_run_id, provider, provider_symbol, timeframe, bar_ts, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [
                (
                    run_id,
                    r.provider,
                    r.provider_symbol,
                    r.timeframe,
                    r.bar_ts,
                    Jsonb(r.payload, dumps=_dumps),
                )
                for r in records
            ],
        )
    return len(records)


def record_gaps(
    conn: psycopg.Connection,
    listing_id: int,
    timeframe: str,
    gaps: list[tuple[datetime, datetime]],
) -> int:
    """Insert gaps not already recorded for (listing_id, timeframe, gap_start, gap_end).

    A matching row counts as recorded whether or not it is resolved. Returns the number of
    new rows. Does not commit.
    """
    inserted = 0
    with conn.cursor() as cur:
        for start, end in dict.fromkeys(gaps):
            cur.execute(
                "INSERT INTO ohlcv_gaps (listing_id, timeframe, gap_start, gap_end) "
                "SELECT %(l)s, %(t)s, %(s)s, %(e)s WHERE NOT EXISTS ("
                "  SELECT 1 FROM ohlcv_gaps WHERE listing_id = %(l)s AND timeframe = %(t)s "
                "  AND gap_start = %(s)s AND gap_end = %(e)s)",
                {"l": listing_id, "t": timeframe, "s": start, "e": end},
            )
            inserted += cur.rowcount
    return inserted
