"""Integration tests for ingestion persistence and instruments (listing-keyed schema)."""

import math
from datetime import UTC, datetime, timedelta

import pytest
from market_ingestion.checkpoint.store import fetch_start, finish_run, last_bar_ts, start_run
from market_ingestion.db import connect
from market_ingestion.instruments.reference import sync_reference
from market_ingestion.instruments.registry import active_listings, find_listing
from market_ingestion.normalization.bars import Bar
from market_ingestion.providers.base import RawRecord
from market_ingestion.publisher.store import insert_raw, record_gaps, upsert_bars

T0 = datetime(2026, 11, 2, tzinfo=UTC)


@pytest.fixture
def conn(fresh_db, migrate):
    migrate(fresh_db)
    c = connect(fresh_db)
    yield c
    c.close()


def _listing(conn, exchange, symbol, active=False, kind="equity"):
    row = conn.execute(
        "INSERT INTO listings (exchange, symbol, kind, is_active) "
        "VALUES (%s, %s, %s, %s) RETURNING listing_id",
        (exchange, symbol, kind, active),
    ).fetchone()
    return row["listing_id"]


def _bars(lid, n=3, close=100.0):
    return [Bar(lid, T0 + timedelta(days=i), 1.0, 2.0, 0.5, close + i, 1000 + i) for i in range(n)]


def test_upsert_bars_idempotent(conn):
    lid = _listing(conn, "NSE", "AAA")
    assert upsert_bars(conn, "1d", _bars(lid)) == 3
    assert upsert_bars(conn, "1d", _bars(lid)) == 3
    assert conn.execute("SELECT count(*) AS n FROM ohlcv_1d").fetchone()["n"] == 3
    upsert_bars(conn, "1d", _bars(lid, close=500.0))
    rows = conn.execute("SELECT close FROM ohlcv_1d ORDER BY ts").fetchall()
    assert [r["close"] for r in rows] == [500.0, 501.0, 502.0]
    assert last_bar_ts(conn, lid, "1d") == T0 + timedelta(days=2)
    assert last_bar_ts(conn, lid, "1w") is None


def test_upsert_bars_full_history_fast(conn):
    lid = _listing(conn, "NSE", "AAA")
    assert upsert_bars(conn, "1d", _bars(lid, n=9000)) == 9000
    assert conn.execute("SELECT count(*) AS n FROM ohlcv_1d").fetchone()["n"] == 9000


def test_raw_append_only(conn):
    lid = _listing(conn, "NSE", "AAA")
    run = start_run(conn, lid, "yahoo", "1d")
    recs = [
        RawRecord("yahoo", "AAA.NS", "1d", T0, {"Open": 1.0, "Close": math.nan, "Volume": 5}),
        RawRecord("yahoo", "AAA.NS", "1d", T0 + timedelta(days=1), {"Open": 2.0}),
    ]
    assert insert_raw(conn, run, recs) == 2
    assert insert_raw(conn, run, recs) == 2
    assert conn.execute("SELECT count(*) AS n FROM raw_eod_bars").fetchone()["n"] == 4
    row = conn.execute("SELECT payload FROM raw_eod_bars ORDER BY id LIMIT 1").fetchone()
    assert row["payload"] == {"Open": 1.0, "Close": None, "Volume": 5}


def test_record_gaps_dedup(conn):
    lid = _listing(conn, "NSE", "AAA")
    g1 = (T0, T0 + timedelta(days=10))
    g2 = (T0 + timedelta(days=20), T0 + timedelta(days=30))
    assert record_gaps(conn, lid, "1d", [g1]) == 1
    assert record_gaps(conn, lid, "1d", [g1, g2]) == 1
    conn.execute("UPDATE ohlcv_gaps SET resolved = true")
    assert record_gaps(conn, lid, "1d", [g1, g2]) == 0
    assert record_gaps(conn, lid, "1w", [g1]) == 1
    assert conn.execute("SELECT count(*) AS n FROM ohlcv_gaps").fetchone()["n"] == 3


def test_run_lifecycle(conn):
    lid = _listing(conn, "NSE", "AAA")
    run = start_run(conn, lid, "yahoo", "1d")
    finish_run(conn, run, rows=3, gaps=1, status="ok", notes="n")
    r = conn.execute("SELECT * FROM ingest_runs WHERE id = %s", (run,)).fetchone()
    assert (r["rows_upserted"], r["gaps_found"], r["status"], r["notes"]) == (3, 1, "ok", "n")
    assert r["finished_at"] is not None


def test_fetch_start():
    assert fetch_start("1d", None) is None
    assert fetch_start("1d", datetime(2026, 11, 10, tzinfo=UTC)).isoformat() == "2026-11-03"
    assert fetch_start("1mo", datetime(2026, 11, 1, tzinfo=UTC)).isoformat() == "2026-09-01"
    assert fetch_start("1mo", datetime(2026, 11, 20, tzinfo=UTC)).isoformat() == "2026-10-01"


def test_active_listings_excludes_inactive(conn):
    a = _listing(conn, "NSE", "ZED", active=True)
    b = _listing(conn, "BSE", "ABC", active=True)
    c = _listing(conn, "NSE", "OFF", active=False)
    d = _listing(conn, "NSE", "NOPS", active=True)
    for lid, tok in ((a, "ZED.NS"), (b, "ABC.BO"), (c, "OFF.NS")):
        conn.execute("INSERT INTO provider_symbols VALUES ('yahoo', %s, %s)", (tok, lid))
    got = active_listings(conn)
    assert [(x.exchange, x.symbol, x.provider_symbol) for x in got] == [
        ("BSE", "ABC", "ABC.BO"),
        ("NSE", "ZED", "ZED.NS"),
    ]
    assert d not in [x.listing_id for x in got]
    assert find_listing(conn, "NSE", "OFF").provider_symbol == "OFF.NS"
    assert find_listing(conn, "NSE", "NOPS") is None


NSE_CSV = (
    "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER,"
    " FACE VALUE\n"
    "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
    "INFY,Infosys Limited,EQ, 08-FEB-1995,5,1, INE009A01021,5\n"
)
BSE_CSV = "symbol,exchange\nINFY,BSE\nGHOST,BSE\n"


def test_sync_reference(conn, tmp_path):
    rel = _listing(conn, "NSE", "RELIANCE", active=True)
    infy_bse = _listing(conn, "BSE", "INFY", active=True)
    ghost = _listing(conn, "BSE", "GHOST")
    nifty = _listing(conn, "NSE", "NIFTY", kind="index")
    nse, bse = tmp_path / "nse.csv", tmp_path / "bse.csv"
    nse.write_text(NSE_CSV)
    bse.write_text(BSE_CSV)

    rep = sync_reference(conn, nse, bse)
    assert rep.companies_upserted == 2
    assert rep.listings_created == 1
    assert rep.listings_linked == 2  # RELIANCE (NSE) and INFY (BSE)
    assert rep.unlinked_bse == ["BSE:GHOST"]

    def company(lid):
        return conn.execute(
            "SELECT c.isin FROM listings l JOIN companies c USING (company_id) "
            "WHERE l.listing_id = %s",
            (lid,),
        ).fetchone()

    assert company(rel)["isin"] == "INE002A01018"
    assert company(infy_bse)["isin"] == "INE009A01021"
    assert company(ghost) is None
    assert company(nifty) is None
    new = conn.execute(
        "SELECT l.*, (SELECT count(*) FROM provider_symbols p WHERE p.listing_id = l.listing_id) "
        "AS ps FROM listings l WHERE exchange = 'NSE' AND symbol = 'INFY'"
    ).fetchone()
    assert new["is_active"] is False and new["ps"] == 0
    assert new["series"] == "EQ" and new["listed_on"].isoformat() == "1995-02-08"
    assert new["kind"] == "equity"
    assert conn.execute("SELECT is_active FROM listings WHERE listing_id = %s", (rel,)).fetchone()[
        "is_active"
    ]

    again = sync_reference(conn, nse, bse)
    assert (again.companies_upserted, again.listings_created, again.listings_linked) == (0, 0, 0)
    assert conn.execute("SELECT count(*) AS n FROM companies").fetchone()["n"] == 2


def test_sync_reference_does_not_repoint_bse(conn, tmp_path):
    other = conn.execute(
        "INSERT INTO companies (name, isin) VALUES ('Other Co', 'INE000X00000') "
        "RETURNING company_id"
    ).fetchone()["company_id"]
    infy_bse = _listing(conn, "BSE", "INFY")
    conn.execute("UPDATE listings SET company_id = %s WHERE listing_id = %s", (other, infy_bse))
    nse, bse = tmp_path / "nse.csv", tmp_path / "bse.csv"
    nse.write_text(NSE_CSV)
    bse.write_text(BSE_CSV)

    rep = sync_reference(conn, nse, bse)
    assert rep.listings_linked == 0
    assert (
        conn.execute(
            "SELECT company_id FROM listings WHERE listing_id = %s", (infy_bse,)
        ).fetchone()["company_id"]
        == other
    )
