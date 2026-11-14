"""Stock page endpoints (per-stock scan and streamed backtest) against a throwaway database."""

import json

import numpy as np
import pandas as pd
import psycopg
import pytest
from app.core.dependencies import get_db
from app.main import app
from app.modules.opportunities import service
from fastapi.testclient import TestClient

N = 320
DATES = pd.date_range("2025-01-01", periods=N, freq="B", tz="UTC")


def _bars(conn, listing_id, closes, last_volume=3_000_000):
    prev, rows = closes[0], []
    for i, (ts, close) in enumerate(zip(DATES, closes, strict=True)):
        volume = last_volume if i == N - 1 else 1_000_000
        high, low = max(prev, close) * 1.006, min(prev, close) * 0.994
        rows.append((ts, listing_id, prev, high, low, close, volume))
        prev = close
    conn.cursor().executemany(
        "INSERT INTO ohlcv_1d (ts, listing_id, open, high, low, close, volume) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        rows,
    )


def _listing(conn, symbol, kind="equity"):
    return conn.execute(
        "INSERT INTO listings (exchange, symbol, kind, is_active) VALUES ('NSE', %s, %s, true) "
        "ON CONFLICT (exchange, symbol) DO UPDATE SET is_active = true RETURNING listing_id",
        (symbol, kind),
    ).fetchone()[0]


@pytest.fixture
def client(fresh_db, migrate):
    migrate(fresh_db)
    rng = np.random.default_rng(1)
    trend = 100 * np.cumprod(1 + 0.0025 + rng.normal(0, 0.006, N - 26))
    flag = trend[-1] * (1 - 0.02 * np.abs(np.sin(np.arange(25) / 3)))
    with psycopg.connect(fresh_db) as conn:
        _bars(conn, _listing(conn, "NIFTY", "index"), 100 * np.cumprod(np.full(N, 1.0004)), 0)
        _bars(conn, _listing(conn, "TESTUP"), np.concatenate([trend, flag, [trend[-1] * 1.04]]))
    conn = psycopg.connect(fresh_db)

    def _get_db():
        yield conn

    app.dependency_overrides[get_db] = _get_db
    service._BACKTEST_CACHE.clear()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        conn.close()


def test_stock_strategies_gives_a_pick_or_a_reason_per_horizon(client):
    body = client.get("/v1/opportunities/stocks/nse/testup").json()
    assert body["symbol"] == "TESTUP" and body["as_of"].startswith(str(DATES[-1].date()))
    assert set(body["horizons"]) == {"next_session", "swing", "long_term"}
    for horizon in body["horizons"].values():
        assert (horizon["pick"] is None) != (horizon["rejection"] is None)
    swing = body["horizons"]["swing"]["pick"]
    assert swing and swing["direction"] == "BUY" and swing["factors"]


def test_unknown_stock_is_404(client):
    assert client.get("/v1/opportunities/stocks/NSE/NOPE").status_code == 404
    assert client.get("/v1/opportunities/stocks/NSE/NOPE/backtest").status_code == 404


def test_backtest_streams_start_progress_done_then_replays_from_cache(client):
    def events():
        with client.stream("GET", "/v1/opportunities/stocks/NSE/TESTUP/backtest") as response:
            assert response.headers["content-type"].startswith("application/x-ndjson")
            return [json.loads(line) for line in response.iter_lines() if line]

    first = events()
    assert first[0]["type"] == "start" and first[0]["sessions"] == N
    assert first[-1]["type"] == "done" and "swing:factor_confluence" in first[-1]["summary"]
    assert [e["type"] for e in first[1:-1]] == ["progress"] * (len(first) - 2)
    trades = [t for e in first[1:-1] for t in e["trades"]]
    horizons = {"next_session", "swing", "long_term"}
    assert all(t["strategy"].split(":")[0] in horizons for t in trades)

    again = events()
    assert all(e["cached"] for e in again)
    assert [{k: v for k, v in e.items() if k != "cached"} for e in again] == first
