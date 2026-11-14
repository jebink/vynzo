"""forecast job: per active equity listing and model, what the model would have predicted over
the chart's past sessions (forecasts every HORIZON sessions) and how wrong it was, upserted into
price_forecast for the listing's last bar date.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from analytics_worker.db import load_daily_bars
from analytics_worker.forecasting.models import MODELS, backtest_path

log = logging.getLogger(__name__)

HORIZON = 30
HISTORY = 500  # sessions of past forecasts: the bars the stock chart loads
MIN_BARS = 300  # a year of history plus the horizon

LISTINGS_SQL = """
SELECT l.listing_id FROM listings l
WHERE l.is_active AND l.kind = 'equity'
  AND EXISTS (SELECT 1 FROM ohlcv_1d b WHERE b.listing_id = l.listing_id)
ORDER BY l.listing_id
"""
UPSERT_SQL = """
INSERT INTO price_forecast (listing_id, model, as_of, horizon, history, metrics)
VALUES (%(listing_id)s, %(model)s, %(as_of)s, %(horizon)s, %(history)s, %(metrics)s)
ON CONFLICT (listing_id, model, as_of) DO UPDATE
SET horizon = EXCLUDED.horizon, history = EXCLUDED.history,
    metrics = EXCLUDED.metrics,
    created_at = now()
"""


@dataclass
class ForecastReport:
    listings: int = 0
    forecast: int = 0
    skipped: int = 0  # too little history
    failed: list[int] = field(default_factory=list)


def forecast_rows(listing_id: int, bars) -> list[dict]:
    closes = bars["close"].astype(float).to_numpy()
    rows = []
    for name, model in MODELS.items():
        path, metrics = backtest_path(model, closes, HORIZON, HISTORY)
        if not np.isfinite(path[~np.isnan(path)]).all():
            log.warning("listing %s: %s gave a non-finite forecast, skipped", listing_id, name)
            continue
        days = bars.index[-len(path) :]
        history = [
            {"date": ts.date().isoformat(), "close": round(float(p), 2)}
            for ts, p in zip(days, path, strict=True)
            if np.isfinite(p)
        ]
        rows.append(
            {
                "listing_id": listing_id,
                "model": name,
                "as_of": bars.index[-1].date(),
                "horizon": HORIZON,
                "history": Jsonb(history),
                "metrics": Jsonb(metrics or {}),
            }
        )
    return rows


def run_forecast(conn: psycopg.Connection, limit: int | None = None) -> ForecastReport:
    ids = [r["listing_id"] for r in conn.execute(LISTINGS_SQL).fetchall()]
    conn.commit()
    ids = ids[:limit] if limit else ids
    report = ForecastReport(listings=len(ids))
    for lid in ids:
        try:
            bars = load_daily_bars(conn, lid).dropna(subset=["close"])
            bars = bars[bars["close"] > 0]  # a zero close (bad tick) would make log prices -inf
            if len(bars) < MIN_BARS:
                report.skipped += 1
                conn.commit()
                continue
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, forecast_rows(lid, bars))
            conn.commit()
            report.forecast += 1
        except Exception:  # one bad listing must not stop the run
            conn.rollback()
            log.exception("forecast failed for listing %s", lid)
            report.failed.append(lid)
    return report
