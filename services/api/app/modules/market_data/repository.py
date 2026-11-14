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


def fetch_overview(
    conn: psycopg.Connection, *, exchange: str | None, points: int, lookback_days: int
) -> list[dict[str, Any]]:
    """Every ingested listing (one with a provider symbol) with its newest `points` daily closes,
    oldest first. Bars are read only within `lookback_days` of the newest bar in ohlcv_1d, so the
    scan touches recent chunks only; a listing with no bar in that window gets empty closes.
    """
    exchange_filter = sql.SQL("AND l.exchange = %(exchange)s") if exchange else sql.SQL("")
    query = sql.SQL("""
        WITH ingested AS (
            SELECT l.listing_id, l.exchange::text AS exchange, l.symbol, l.kind,
                   c.name AS company_name, l.is_active, c.sector, c.shares_outstanding
            FROM listings l
            LEFT JOIN companies c USING (company_id)
            WHERE EXISTS (SELECT 1 FROM provider_symbols p WHERE p.listing_id = l.listing_id)
            {exchange_filter}
        ),
        recent AS (
            SELECT b.listing_id, b.ts, b.close, b.volume,
                   row_number() OVER (PARTITION BY b.listing_id ORDER BY b.ts DESC) AS rn
            FROM ohlcv_1d b
            WHERE b.listing_id IN (SELECT listing_id FROM ingested)
              AND b.ts > (SELECT max(ts) FROM ohlcv_1d) - make_interval(days => %(lookback)s)
        )
        SELECT i.listing_id, i.exchange, i.symbol, i.kind, i.company_name, i.is_active,
               i.sector, i.shares_outstanding,
               max(r.ts) AS latest_ts,
               coalesce(array_agg(r.close ORDER BY r.ts) FILTER (WHERE r.ts IS NOT NULL),
                        '{{}}') AS closes,
               (array_agg(r.volume ORDER BY r.ts DESC))[1] AS volume
        FROM ingested i
        LEFT JOIN recent r ON r.listing_id = i.listing_id AND r.rn <= %(points)s
        GROUP BY i.listing_id, i.exchange, i.symbol, i.kind, i.company_name, i.is_active,
                 i.sector, i.shares_outstanding
        ORDER BY i.symbol, i.exchange
    """).format(exchange_filter=exchange_filter)
    params: dict[str, Any] = {"points": points, "lookback": lookback_days}
    if exchange:
        params["exchange"] = exchange.upper()
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, params).fetchall()
