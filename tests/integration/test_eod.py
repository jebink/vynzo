"""Integration tests for the ingestion jobs (eod, backfill, freshness) with a fake provider."""

from datetime import UTC, date, datetime

import psycopg
import pytest
from market_ingestion import pipeline
from market_ingestion.db import connect
from market_ingestion.freshness import check_freshness
from market_ingestion.instruments.registry import active_listings
from market_ingestion.pipeline import ingest_listing, run_backfill, run_eod
from market_ingestion.providers.base import RawRecord

NOW = datetime(2026, 11, 11, 11, 30, tzinfo=UTC)  # 17:00 IST
D = lambda day: datetime(2026, 11, day, tzinfo=UTC)  # noqa: E731


def _rec(sym, tf, ts, close=100.0):
    payload = {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000}
    return RawRecord("yahoo", sym, tf, ts, payload)


class FakeProvider:
    name = "yahoo"

    def __init__(self, data=None):
        self.data = data or {}
        self.calls: list[tuple[str, str, date | None, date]] = []

    def fetch_bars(self, provider_symbol, timeframe, start, end):
        self.calls.append((provider_symbol, timeframe, start, end))
        if provider_symbol == "BOOM.NS":
            raise RuntimeError("provider exploded")
        return list(self.data.get((provider_symbol, timeframe), []))


@pytest.fixture
def url(fresh_db, migrate, without_reference_listings):
    migrate(fresh_db)
    without_reference_listings(fresh_db)
    return fresh_db


def _add(url, symbol, *, bars=(), active=True):
    with connect(url) as conn:
        lid = conn.execute(
            "INSERT INTO listings (exchange, symbol, kind, is_active) "
            "VALUES ('NSE', %s, 'equity', %s) RETURNING listing_id",
            (symbol, active),
        ).fetchone()["listing_id"]
        conn.execute(
            "INSERT INTO provider_symbols (provider, provider_symbol, listing_id) "
            "VALUES ('yahoo', %s, %s)",
            (f"{symbol}.NS", lid),
        )
        for ts in bars:
            conn.execute(
                "INSERT INTO ohlcv_1d (listing_id, ts, open, high, low, close, volume) "
                "VALUES (%s, %s, 1, 2, 1, 1, 1)",
                (lid, ts),
            )
        conn.commit()
    return lid


def _scalar(url, query, params=()):
    with connect(url) as conn:
        return conn.execute(query, params).fetchone()["n"]


def test_eod_writes_everything(url):
    _add(url, "RELIANCE", bars=[D(5)])
    fake = FakeProvider(
        {("RELIANCE.NS", "1d"): [_rec("RELIANCE.NS", "1d", D(5)), _rec("RELIANCE.NS", "1d", D(10))]}
    )
    report = run_eod(url, fake, workers=2, now=NOW)
    assert report.listings == 1 and report.failed == [] and report.rows == 2
    starts = {tf: s for _, tf, s, _ in fake.calls}
    assert starts["1d"] == date(2026, 10, 29)
    assert starts["1w"] is None and starts["1mo"] is None
    assert _scalar(url, "SELECT count(*) AS n FROM ohlcv_1d") == 2
    assert _scalar(url, "SELECT count(*) AS n FROM raw_eod_bars") == 2
    with connect(url) as conn:
        runs = conn.execute("SELECT provider, status, timeframe FROM ingest_runs").fetchall()
    assert len(runs) == 3 and {r["status"] for r in runs} == {"ok"}
    assert {r["provider"] for r in runs} == {"yahoo"}


def test_eod_full_history_for_new_listing(url):
    _add(url, "NEWCO")
    fake = FakeProvider()
    run_eod(url, fake, now=NOW)
    assert [s for _, tf, s, _ in fake.calls if tf == "1d"] == [None]


def test_eod_empty_response_ok(url):
    _add(url, "RELIANCE")
    report = run_eod(url, FakeProvider(), now=NOW)
    assert report.rows == 0 and report.failed == []
    with connect(url) as conn:
        runs = conn.execute("SELECT status, rows_upserted, gaps_found FROM ingest_runs").fetchall()
    assert all(
        r["status"] == "ok" and r["rows_upserted"] == 0 and r["gaps_found"] == 0 for r in runs
    )


def test_eod_idempotent(url):
    _add(url, "RELIANCE")
    fake = FakeProvider(
        {("RELIANCE.NS", "1d"): [_rec("RELIANCE.NS", "1d", D(d)) for d in (3, 4, 5)]}
    )
    run_eod(url, fake, now=NOW)
    run_eod(url, fake, now=NOW)
    assert _scalar(url, "SELECT count(*) AS n FROM ohlcv_1d") == 3


def test_eod_records_gaps(url):
    _add(url, "RELIANCE")
    fake = FakeProvider({("RELIANCE.NS", "1d"): [_rec("RELIANCE.NS", "1d", D(d)) for d in (2, 9)]})
    run_eod(url, fake, now=NOW)
    assert _scalar(url, "SELECT count(*) AS n FROM ohlcv_gaps WHERE NOT resolved") == 1


def test_eod_isolates_failure(url):
    _add(url, "RELIANCE")
    boom = _add(url, "BOOM")
    fake = FakeProvider({("RELIANCE.NS", "1d"): [_rec("RELIANCE.NS", "1d", D(5))]})
    report = run_eod(url, fake, workers=2, now=NOW)
    assert report.failed == ["NSE:BOOM"] and report.listings == 2
    assert _scalar(url, "SELECT count(*) AS n FROM ohlcv_1d") == 1
    with connect(url) as conn:
        rows = conn.execute(
            "SELECT status, notes FROM ingest_runs WHERE listing_id = %s", (boom,)
        ).fetchall()
    assert rows and all(r["status"] == "error" for r in rows)
    assert "provider exploded" in rows[0]["notes"]


def test_eod_connect_failure_is_a_failed_listing(url, monkeypatch):
    _add(url, "RELIANCE")
    _add(url, "TCS")
    with connect(url) as conn:
        listings = sorted(active_listings(conn), key=lambda x: x.symbol)  # RELIANCE, TCS
    calls = 0
    real_connect = pipeline.connect

    def flaky_connect(db_url):
        nonlocal calls
        calls += 1
        if calls == 2:  # the worker connection for TCS (workers=1 keeps the order)
            raise psycopg.OperationalError("connection refused")
        return real_connect(db_url)

    monkeypatch.setattr(pipeline, "connect", flaky_connect)
    fake = FakeProvider({("RELIANCE.NS", "1d"): [_rec("RELIANCE.NS", "1d", D(5))]})
    report = run_eod(url, fake, workers=1, now=NOW, only=listings)
    assert report.listings == 2 and report.failed == ["NSE:TCS"] and report.rows == 1
    assert {sym for sym, *_ in fake.calls} == {"RELIANCE.NS"}


def test_listing_task_crash_becomes_error_results(url, monkeypatch):
    _add(url, "RELIANCE")

    def crash(conn, provider, listing, timeframe, end):
        raise RuntimeError("worker crashed")

    monkeypatch.setattr(pipeline, "ingest_listing", crash)
    report = run_eod(url, FakeProvider(), workers=2, now=NOW)
    assert report.listings == 1 and report.failed == ["NSE:RELIANCE"] and report.rows == 0


def test_error_row_survives_rollback(url):
    boom = _add(url, "BOOM")
    with connect(url) as conn:
        listing = next(x for x in active_listings(conn) if x.listing_id == boom)
        res = ingest_listing(conn, FakeProvider(), listing, "1d", date(2026, 11, 10))
    assert res.status == "error" and "provider exploded" in res.error
    assert _scalar(url, "SELECT count(*) AS n FROM ingest_runs WHERE status = 'error'") == 1
    assert _scalar(url, "SELECT count(*) AS n FROM ingest_runs WHERE status = 'running'") == 0


def test_backfill_resolves_gap(url):
    lid = _add(url, "RELIANCE", bars=[D(2), D(14)])
    with connect(url) as conn:
        conn.execute(
            "INSERT INTO ohlcv_gaps (listing_id, timeframe, gap_start, gap_end) "
            "VALUES (%s, '1d', %s, %s)",
            (lid, D(2), D(14)),
        )
        conn.commit()
    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    fake = FakeProvider(
        {("RELIANCE.NS", "1d"): [_rec("RELIANCE.NS", "1d", D(d)) for d in range(3, 14)]}
    )
    report = run_backfill(url, fake, now=now)
    assert report.failed == []
    assert _scalar(url, "SELECT count(*) AS n FROM ohlcv_gaps WHERE resolved") == 1
    assert _scalar(url, "SELECT count(*) AS n FROM ohlcv_1d") == 13


def test_backfill_gap_unresolved_when_provider_empty(url):
    lid = _add(url, "RELIANCE", bars=[D(2), D(14)])
    with connect(url) as conn:
        conn.execute(
            "INSERT INTO ohlcv_gaps (listing_id, timeframe, gap_start, gap_end) "
            "VALUES (%s, '1d', %s, %s)",
            (lid, D(2), D(14)),
        )
        conn.commit()
    report = run_backfill(url, FakeProvider(), now=NOW)
    assert report.failed == []
    assert _scalar(url, "SELECT count(*) AS n FROM ohlcv_gaps WHERE NOT resolved") == 1


def test_backfill_listing_filter(url):
    _add(url, "RELIANCE")
    _add(url, "TCS")
    fake = FakeProvider()
    report = run_backfill(url, fake, listing="NSE:RELIANCE", now=NOW)
    assert report.listings == 1
    assert {sym for sym, *_ in fake.calls} == {"RELIANCE.NS"}
    assert {tf for _, tf, *_ in fake.calls} == {"1d", "1w", "1mo"}


def test_freshness_stale_and_fresh(url):
    wed = datetime(2026, 11, 11, 13, 30, tzinfo=UTC)  # 19:00 IST
    lid = _add(url, "RELIANCE", bars=[D(9)])  # Monday
    with connect(url) as conn:
        res = check_freshness(conn, now=wed)
        assert not res.fresh and res.latest == date(2026, 11, 9)
        assert res.expected == date(2026, 11, 11) and res.pushed is None
        conn.execute(
            "INSERT INTO ohlcv_1d (listing_id, ts, open, high, low, close, volume) "
            "VALUES (%s, %s, 1, 2, 1, 1, 1)",
            (lid, D(10)),
        )
        assert check_freshness(conn, now=wed).fresh


def test_freshness_push_failure_is_not_fatal(url):
    with connect(url) as conn:
        res = check_freshness(conn, now=NOW, push_url="http://127.0.0.1:9/push")
    assert res.pushed is False and not res.fresh and res.latest is None
