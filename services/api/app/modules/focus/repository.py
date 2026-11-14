"""SQL for the focus module: one row per active equity with its latest news sentiment, recent
daily bars and next corporate event."""

from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

BARS = 30  # newest daily bars per listing
NEWS_MAX_AGE_DAYS = 3  # older sentiment rows don't count as "in the news now"

_CANDIDATES = """
WITH sentiment AS (
    SELECT DISTINCT ON (listing_id) listing_id, as_of, strength, meta
    FROM signal
    WHERE signal_type = 'SENTIMENT' AND as_of >= %(today)s - make_interval(days => %(news_age)s)
    ORDER BY listing_id, as_of DESC
),
recent AS (
    SELECT listing_id, ts, close, volume,
           row_number() OVER (PARTITION BY listing_id ORDER BY ts DESC) AS rn
    FROM ohlcv_1d
    WHERE ts > (SELECT max(ts) FROM ohlcv_1d) - interval '75 days'
),
bars AS (
    SELECT listing_id, max(ts) AS latest_ts,
           array_agg(close ORDER BY ts) AS closes, array_agg(volume ORDER BY ts) AS volumes
    FROM recent WHERE rn <= %(bars)s GROUP BY listing_id
),
next_event AS (
    SELECT DISTINCT ON (listing_id) listing_id, event_type, event_date, details
    FROM corporate_event
    WHERE event_date >= %(today)s AND event_date <= %(today)s + %(event_days)s
    ORDER BY listing_id, event_date
)
SELECT l.listing_id, l.exchange::text AS exchange, l.symbol, c.name AS company_name, c.sector,
       b.latest_ts, b.closes, b.volumes,
       s.as_of AS news_as_of, s.strength AS sentiment, s.meta AS news,
       e.event_type, e.event_date, e.details AS event_details
FROM listings l
JOIN bars b USING (listing_id)
LEFT JOIN companies c USING (company_id)
LEFT JOIN sentiment s USING (listing_id)
LEFT JOIN next_event e USING (listing_id)
WHERE l.is_active AND l.kind = 'equity'
"""


def candidates(conn: psycopg.Connection, today: date, event_days: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            _CANDIDATES,
            {"today": today, "news_age": NEWS_MAX_AGE_DAYS, "bars": BARS, "event_days": event_days},
        ).fetchall()
