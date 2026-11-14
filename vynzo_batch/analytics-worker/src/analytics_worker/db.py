"""Database helpers: connection and daily-bar loading."""

import pandas as pd
import psycopg
from psycopg.rows import dict_row

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]


def connect(url: str) -> psycopg.Connection:
    """Open a connection with dict rows and autocommit off (the caller owns the transaction)."""
    return psycopg.connect(url, row_factory=dict_row, autocommit=False)


def load_daily_bars(conn: psycopg.Connection, listing_id: int) -> pd.DataFrame:
    """All 1d bars of a listing: open/high/low/close/volume, sorted UTC ts index."""
    rows = conn.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv_1d WHERE listing_id = %s ORDER BY ts",
        (listing_id,),
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=BAR_COLUMNS)
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()[BAR_COLUMNS]
