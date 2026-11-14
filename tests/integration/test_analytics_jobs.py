from datetime import UTC, datetime, timedelta

import psycopg
from analytics_worker.db import connect
from analytics_worker.indicators.job import run_indicators
from analytics_worker.signals.high_volume_buy import run_high_volume_buy

START = datetime(2026, 1, 1, tzinfo=UTC)


def _seed(url: str, bars: int, *, spike: bool = False) -> int:
    with psycopg.connect(url) as conn:
        lid = conn.execute(
            "INSERT INTO listings (exchange, symbol, kind, is_active) "
            "VALUES ('NSE', 'TESTCO', 'equity', true) RETURNING listing_id"
        ).fetchone()[0]
        rows = []
        for i in range(bars):
            close = 100.0 + i * 0.5
            vol = 1000
            if spike and i >= bars - 3:
                vol = 5000
            rows.append(
                (START + timedelta(days=i), lid, close - 0.2, close + 1, close - 1, close, vol)
            )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ohlcv_1d (ts, listing_id, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                rows,
            )
        conn.commit()
    return lid


def test_indicators_short_history_nulls(fresh_db, migrate):
    migrate(fresh_db)
    lid = _seed(fresh_db, 50)
    with connect(fresh_db) as conn:
        report = run_indicators(conn)
    assert (report.listings, report.rows, report.failed) == (1, 15, [])
    with psycopg.connect(fresh_db) as conn:
        n, nulls, versions = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE ret_126 IS NULL), "
            "array_agg(DISTINCT calc_version) FROM ta_daily WHERE listing_id = %s",
            (lid,),
        ).fetchone()
    # ema_200 is a min_periods-free ewm in vinzo-core, so it is defined from bar 1; ret_126
    # (126-bar shift) is the column that is NULL on short history.
    assert n == 15 and nulls == 15
    assert versions == ["ta-1"]


def test_indicators_picks_up_revised_bar(fresh_db, migrate):
    migrate(fresh_db)
    lid = _seed(fresh_db, 50)
    with connect(fresh_db) as conn:
        run_indicators(conn)
    with psycopg.connect(fresh_db) as conn:
        before = conn.execute(
            "SELECT ema_9 FROM ta_daily WHERE listing_id = %s ORDER BY ts DESC LIMIT 1", (lid,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE ohlcv_1d SET close = close + 10 WHERE listing_id = %s AND ts = "
            "(SELECT max(ts) FROM ohlcv_1d WHERE listing_id = %s)",
            (lid, lid),
        )
        conn.commit()
    with connect(fresh_db) as conn:
        report = run_indicators(conn)
    assert report.rows == 15
    with psycopg.connect(fresh_db) as conn:
        after = conn.execute(
            "SELECT ema_9 FROM ta_daily WHERE listing_id = %s ORDER BY ts DESC LIMIT 1", (lid,)
        ).fetchone()[0]
    assert after != before


def test_indicators_overwrites_legacy_row(fresh_db, migrate):
    migrate(fresh_db)
    lid = _seed(fresh_db, 50)
    ts = START + timedelta(days=45)
    with psycopg.connect(fresh_db) as conn:
        conn.execute(
            "INSERT INTO ta_daily (ts, listing_id, rsi_14, calc_version) "
            "VALUES (%s, %s, 1.0, 'legacy-vinzo-core')",
            (ts, lid),
        )
        conn.commit()
    with connect(fresh_db) as conn:
        run_indicators(conn)
    with psycopg.connect(fresh_db) as conn:
        version = conn.execute(
            "SELECT calc_version FROM ta_daily WHERE listing_id = %s AND ts = %s", (lid, ts)
        ).fetchone()[0]
    assert version == "ta-1"


def test_hvb_upsert_idempotent(fresh_db, migrate):
    migrate(fresh_db)
    _seed(fresh_db, 40, spike=True)

    def count():
        with psycopg.connect(fresh_db) as conn:
            return conn.execute(
                "SELECT count(*) FROM signal WHERE signal_type = 'HIGH_VOLUME_BUY'"
            ).fetchone()[0]

    with connect(fresh_db) as conn:
        first = run_high_volume_buy(conn, days=5)
    c1 = count()
    assert first.found == c1 == 3
    with connect(fresh_db) as conn:
        run_high_volume_buy(conn, days=5)
    assert count() == c1
    with psycopg.connect(fresh_db) as conn:
        as_of, version = conn.execute(
            "SELECT as_of, calc_version FROM signal ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    assert as_of == START + timedelta(days=39)
    assert version == "hvb-1"
