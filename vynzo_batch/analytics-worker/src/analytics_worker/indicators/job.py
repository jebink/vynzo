"""indicators job: compute daily TA per listing and upsert the newest rows into ta_daily."""

import logging
import math
from dataclasses import dataclass, field

import pandas as pd
import psycopg

from analytics_worker.db import load_daily_bars
from analytics_worker.indicators.ta import TA_COLUMNS, compute_ta_frame

log = logging.getLogger(__name__)

# Every active listing with at least one 1d bar. Not gated on staleness: the eod job revises
# recent bars in place (same-day re-runs, holidays), and those revisions must reach ta_daily.
LISTINGS_SQL = """
SELECT l.listing_id
FROM listings l
WHERE l.is_active AND EXISTS (SELECT 1 FROM ohlcv_1d b WHERE b.listing_id = l.listing_id)
ORDER BY l.listing_id
"""

_COLS = ["listing_id", "ts", *TA_COLUMNS, "calc_version"]
UPSERT_SQL = f"""
INSERT INTO ta_daily ({", ".join(_COLS)}, computed_at)
VALUES ({", ".join(f"%({c})s" for c in _COLS)}, now())
ON CONFLICT (listing_id, ts) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in [*TA_COLUMNS, "calc_version"])},
    computed_at = now()
"""


@dataclass
class IndicatorsReport:
    listings: int
    rows: int
    failed: list[int] = field(default_factory=list)


def _num(v) -> float | None:
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) or math.isinf(f) else f


def _payload(listing_id: int, ta: pd.DataFrame, tail: int, calc_version: str) -> list[dict]:
    out = []
    for ts, row in ta.tail(tail).iterrows():
        item = {
            "listing_id": listing_id,
            "ts": pd.Timestamp(ts).to_pydatetime(),
            "calc_version": calc_version,
        }
        for col in TA_COLUMNS:
            item[col] = _num(row[col])
        out.append(item)
    return out


def run_indicators(
    conn: psycopg.Connection,
    *,
    tail: int = 15,
    calc_version: str = "ta-1",
    listing_ids: list[int] | None = None,
) -> IndicatorsReport:
    """Recompute TA over full history and upsert the last ``tail`` rows per listing.

    With ``listing_ids=None`` every active listing that has 1d bars is recomputed (no staleness
    gate), so in-place bar revisions and legacy-vinzo-core rows are refreshed.
    """
    if listing_ids is None:
        ids = [r["listing_id"] for r in conn.execute(LISTINGS_SQL).fetchall()]
        conn.commit()
    else:
        ids = list(listing_ids)

    rows = 0
    failed: list[int] = []
    for lid in ids:
        try:
            bars = load_daily_bars(conn, lid)
            if bars.empty:
                conn.commit()
                continue
            payload = _payload(lid, compute_ta_frame(bars), tail, calc_version)
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, payload)
            conn.commit()
            rows += len(payload)
        except Exception:
            conn.rollback()
            log.exception("indicators failed for listing %s", lid)
            failed.append(lid)
    return IndicatorsReport(listings=len(ids), rows=rows, failed=failed)
