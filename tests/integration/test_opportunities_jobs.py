"""opportunities and opportunity-outcomes jobs against a throwaway migrated database."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import psycopg
import pytest
from analytics_worker.db import connect
from analytics_worker.opportunities.engine import CALC_VERSION
from analytics_worker.opportunities.job import run_opportunities, run_outcomes

N = 320
DATES = pd.date_range("2025-01-01", periods=N, freq="B", tz="UTC")


def _breakout_closes(seed=1):
    """Uptrend, 25-session flag, then a breakout close (same shape as the engine unit tests)."""
    rng = np.random.default_rng(seed)
    trend = 100 * np.cumprod(1 + 0.0025 + rng.normal(0, 0.006, N - 26))
    top = trend[-1]
    flag = top * (1 - 0.02 * np.abs(np.sin(np.arange(25) / 3)))
    return np.concatenate([trend, flag, [top * 1.04]])


def _rows(listing_id, closes, dates, *, last_volume=3_000_000):
    rows = []
    prev = closes[0]
    for i, (ts, close) in enumerate(zip(dates, closes, strict=True)):
        high, low = max(prev, close) * 1.006, min(prev, close) * 0.994
        volume = last_volume if i == len(closes) - 1 else 1_000_000
        rows.append((ts.to_pydatetime(), listing_id, prev, high, low, close, volume))
        prev = close
    return rows


def _insert_bars(conn, rows):
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ohlcv_1d (ts, listing_id, open, high, low, close, volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )


def _listing(conn, exchange, symbol, kind="equity", company_id=None):
    return conn.execute(
        "INSERT INTO listings (exchange, symbol, kind, company_id, is_active) "
        "VALUES (%s, %s, %s, %s, true) ON CONFLICT (exchange, symbol) "
        "DO UPDATE SET is_active = true RETURNING listing_id",
        (exchange, symbol, kind, company_id),
    ).fetchone()[0]


@pytest.fixture
def seeded(fresh_db, migrate):
    migrate(fresh_db)
    ids = {}
    with psycopg.connect(fresh_db) as conn:
        company = conn.execute(
            "INSERT INTO companies (name, isin) VALUES ('Test Up Ltd', 'INE000T01001') "
            "RETURNING company_id"
        ).fetchone()[0]
        ids["nifty"] = _listing(conn, "NSE", "NIFTY", "index")
        _insert_bars(
            conn, _rows(ids["nifty"], 100 * np.cumprod(np.full(N, 1.0004)), DATES, last_volume=0)
        )
        closes = _breakout_closes()
        ids["up"] = _listing(conn, "NSE", "TESTUP", company_id=company)
        _insert_bars(conn, _rows(ids["up"], closes, DATES))
        # Same company on BSE: must not produce a duplicate pick.
        ids["up_bse"] = _listing(conn, "BSE", "TESTUP", company_id=company)
        _insert_bars(conn, _rows(ids["up_bse"], closes, DATES))
        # Stale: its last bar is a week before the latest session.
        ids["stale"] = _listing(conn, "NSE", "STALE")
        _insert_bars(conn, _rows(ids["stale"], closes[:-5], DATES[:-5]))
    return fresh_db, ids


def _picks(url):
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT listing_id, horizon, direction, status, as_of, calc_version, regime->>'label', "
            "jsonb_array_length(reasons), inputs->>'close' FROM opportunity ORDER BY horizon"
        ).fetchall()


def test_opportunities_job_writes_deduped_fresh_picks(seeded):
    url, ids = seeded
    with connect(url) as conn:
        report = run_opportunities(conn)
    assert report.as_of == DATES[-1].date().isoformat()
    assert report.stale == 1 and report.skipped_duplicates == 1 and report.failed == []
    picks = _picks(url)
    assert {p[0] for p in picks} == {ids["up"]}
    swing = next(p for p in picks if p[1] == "swing")
    assert swing[2:4] == ("BUY", "actionable")
    assert swing[4] == DATES[-1].to_pydatetime()
    assert swing[5] == CALC_VERSION and swing[6] in ("bullish", "neutral")
    assert swing[7] >= 3 and float(swing[8]) > 0
    assert report.found["swing"] == 1

    # Re-running the same session replaces the day's picks instead of adding duplicates.
    with connect(url) as conn:
        run_opportunities(conn)
    assert len(_picks(url)) == len(picks)


def test_opportunities_as_of_an_earlier_session(seeded):
    url, ids = seeded
    with connect(url) as conn:
        report = run_opportunities(conn, as_of=DATES[-6].date())
    # TESTUP has no breakout yet and STALE is current at that date; nothing is from the future.
    assert report.as_of == DATES[-6].date().isoformat()
    for _, _, _, _, as_of, *_ in _picks(url):
        assert as_of == DATES[-6].to_pydatetime()


def test_outcomes_close_picks_from_later_bars(seeded):
    url, ids = seeded
    with connect(url) as conn:
        run_opportunities(conn)
    with psycopg.connect(url) as conn:
        pid, lo, hi, target = conn.execute(
            "SELECT id, entry_low, entry_high, targets[1] FROM opportunity WHERE horizon = 'swing'"
        ).fetchone()
        # Next session trades inside the entry range, the one after runs through the target.
        later = pd.date_range(DATES[-1] + pd.offsets.BDay(1), periods=2, freq="B", tz="UTC")
        mid = (lo + hi) / 2
        _insert_bars(
            conn,
            [
                (later[0].to_pydatetime(), ids["up"], mid, hi, lo, mid, 1_000_000),
                (
                    later[1].to_pydatetime(),
                    ids["up"],
                    mid,
                    target * 1.01,
                    mid * 0.999,
                    target,
                    1_000_000,
                ),
            ],
        )
    with connect(url) as conn:
        report = run_outcomes(conn)
    assert report.closed.get("target_hit") == 1
    with psycopg.connect(url) as conn:
        status, entry, exit_price, ret, held = conn.execute(
            "SELECT status, entry_price, exit_price, return_pct, sessions_held "
            "FROM opportunity_outcome WHERE opportunity_id = %s",
            (pid,),
        ).fetchone()
    assert status == "target_hit" and entry == pytest.approx(mid)
    assert exit_price == pytest.approx(target) and ret > 0 and held == 2
    # Idempotent: a closed pick is not evaluated again.
    with connect(url) as conn:
        assert run_outcomes(conn).closed == {}


def test_jobs_with_no_data(fresh_db, migrate):
    migrate(fresh_db)
    with connect(fresh_db) as conn:
        report = run_opportunities(conn)
        assert report.as_of is None and report.listings == 0
        assert run_outcomes(conn).closed == {}


def test_as_of_is_utc_midnight():
    assert DATES[-1].tzinfo is not None and DATES[-1] == datetime(2026, 3, 24, tzinfo=UTC)


def test_migration_adds_regime_index_listings(fresh_db, migrate):
    migrate(fresh_db)
    with psycopg.connect(fresh_db) as conn:
        rows = conn.execute(
            "SELECT l.symbol, l.kind, l.is_active, p.provider_symbol FROM listings l "
            "JOIN provider_symbols p USING (listing_id) "
            "WHERE l.symbol IN ('BANKNIFTY', 'INDIAVIX') ORDER BY l.symbol"
        ).fetchall()
    assert rows == [
        ("BANKNIFTY", "index", True, "^NSEBANK"),
        ("INDIAVIX", "index", True, "^INDIAVIX"),
    ]
