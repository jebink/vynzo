"""Persistence for market_data: SQL against PostgreSQL/TimescaleDB. Schema lives in
database/postgres.
"""

from datetime import date, timedelta
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

BAR_TABLES = {
    "1d": "ohlcv_1d",
    "1w": "ohlcv_1w",
    "1mo": "ohlcv_1mo",
    "75m": "ohlcv_75m",
    "15m": "ohlcv_15m",
    "5m": "ohlcv_5m",
    "1m": "ohlcv_1m",
}

INDICATOR_COLUMNS = (
    "ts, calc_version, rsi_14, ema_9, ema_21, ema_50, ema_200, macd, macd_signal, macd_hist, "
    "atr_14, vwap, adx_14, plus_di_14, minus_di_14, rvol_20, donchian_high_20, donchian_low_20, "
    "donchian_high_55, bb_width, obv, ema200_slope_20, extension_atr, ret_126"
)


def _newest_ascending(
    conn: psycopg.Connection,
    table: str,
    columns: sql.Composable,
    listing_id: int,
    limit: int,
    end: date | None,
) -> list[dict[str, Any]]:
    """Newest `limit` rows via the (listing_id, ts DESC) index, returned oldest first."""
    query = sql.SQL("SELECT {cols} FROM {table} WHERE listing_id = %(lid)s").format(
        cols=columns, table=sql.Identifier("public", table)
    )
    params: dict[str, Any] = {"lid": listing_id, "limit": limit}
    if end is not None:
        query += sql.SQL(" AND ts < %(end)s")
        params["end"] = f"{end + timedelta(days=1)}T00:00:00+00:00"
    query += sql.SQL(" ORDER BY ts DESC LIMIT %(limit)s")
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(query, params).fetchall()
    rows.reverse()
    return rows


def fetch_bars(
    conn: psycopg.Connection, timeframe: str, listing_id: int, limit: int, end: date | None
) -> list[dict[str, Any]]:
    cols = sql.SQL("ts, open, high, low, close, volume")
    return _newest_ascending(conn, BAR_TABLES[timeframe], cols, listing_id, limit, end)


def fetch_indicators(
    conn: psycopg.Connection, listing_id: int, limit: int, end: date | None
) -> list[dict[str, Any]]:
    cols = sql.SQL(INDICATOR_COLUMNS)
    return _newest_ascending(conn, "ta_daily", cols, listing_id, limit, end)
