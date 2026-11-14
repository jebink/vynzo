"""HIGH_VOLUME_BUY detector, ported from vinzo-core.

Rule (daily bars): green day (close >= open) and up day (close > previous close) and
volume >= multiplier x average volume of the previous ``lookback`` bars.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from analytics_worker.db import load_daily_bars

log = logging.getLogger(__name__)

SIGNAL_TYPE = "HIGH_VOLUME_BUY"

LISTINGS_SQL = """
SELECT l.listing_id
FROM listings l
WHERE l.is_active AND EXISTS (SELECT 1 FROM ohlcv_1d b WHERE b.listing_id = l.listing_id)
ORDER BY l.listing_id
"""

UPSERT_SQL = """
INSERT INTO signal
    (listing_id, signal_type, as_of, strength, price, volume, avg_volume, rationale, meta,
     calc_version)
VALUES
    (%(listing_id)s, %(signal_type)s, %(as_of)s, %(strength)s, %(price)s, %(volume)s,
     %(avg_volume)s, %(rationale)s, %(meta)s, %(calc_version)s)
ON CONFLICT (listing_id, signal_type, as_of) DO UPDATE SET
    strength = EXCLUDED.strength,
    price = EXCLUDED.price,
    volume = EXCLUDED.volume,
    avg_volume = EXCLUDED.avg_volume,
    rationale = EXCLUDED.rationale,
    meta = EXCLUDED.meta,
    calc_version = EXCLUDED.calc_version,
    created_at = now()
"""


@dataclass
class HvbReport:
    scanned: int
    found: int
    failed: list[int] = field(default_factory=list)
    listings: int = 0


def evaluate_at_index(
    df: pd.DataFrame, idx: int, *, lookback: int = 20, multiplier: float = 2.0
) -> dict[str, Any] | None:
    if idx < lookback:
        return None
    last = df.iloc[idx]
    window = df.iloc[idx - lookback : idx]
    avg_vol = float(window["volume"].mean())
    if avg_vol <= 0:
        return None

    vol = int(last["volume"])
    strength = vol / avg_vol
    close = float(last["close"])
    open_ = float(last["open"])
    prev_close = float(df.iloc[idx - 1]["close"])

    green = close >= open_
    up_day = close > prev_close
    spike = strength >= multiplier
    if not (green and up_day and spike):
        return None

    return {
        "as_of": pd.Timestamp(last.name).to_pydatetime(),
        "strength": round(strength, 3),
        "price": close,
        "volume": vol,
        "avg_volume": round(avg_vol, 1),
        "rationale": (
            f"High volume buy: vol {vol:,} = {strength:.2f}× "
            f"{lookback}d avg ({avg_vol:,.0f}); close {close:.2f} > "
            f"open {open_:.2f} and prev close {prev_close:.2f}"
        ),
        "meta": {
            "lookback": lookback,
            "multiplier": multiplier,
            "open": open_,
            "high": float(last["high"]),
            "low": float(last["low"]),
            "prev_close": prev_close,
            "change_pct": round((close / prev_close - 1.0) * 100, 3),
        },
    }


def run_high_volume_buy(
    conn: psycopg.Connection,
    *,
    days: int = 1,
    as_of: date | None = None,
    lookback: int = 20,
    multiplier: float = 2.0,
    calc_version: str = "hvb-1",
) -> HvbReport:
    """Scan active listings; days=1 is the latest bar, days>1 walks back that many sessions."""
    days = max(1, days)
    ids = [r["listing_id"] for r in conn.execute(LISTINGS_SQL).fetchall()]
    conn.commit()

    scanned = found = 0
    failed: list[int] = []
    for lid in ids:
        try:
            df = load_daily_bars(conn, lid)
            if as_of is not None and not df.empty:
                cutoff = pd.Timestamp(as_of, tz="UTC") + pd.Timedelta(days=1)
                df = df[df.index < cutoff]
            if len(df) < lookback + 1:
                conn.commit()
                continue
            hits = []
            n_scanned = 0
            for idx in range(max(lookback, len(df) - days), len(df)):
                n_scanned += 1
                row = evaluate_at_index(df, idx, lookback=lookback, multiplier=multiplier)
                if row:
                    row.update(
                        listing_id=lid,
                        signal_type=SIGNAL_TYPE,
                        calc_version=calc_version,
                        meta=Jsonb(row["meta"]),
                    )
                    hits.append(row)
            if hits:
                with conn.cursor() as cur:
                    cur.executemany(UPSERT_SQL, hits)
            conn.commit()
            scanned += n_scanned
            found += len(hits)
        except Exception:
            conn.rollback()
            log.exception("high-volume-buy failed for listing %s", lid)
            failed.append(lid)
    return HvbReport(scanned=scanned, found=found, failed=failed, listings=len(ids))
