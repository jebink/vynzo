"""API tests for instruments, market data and signals against a throwaway migrated database."""

import psycopg
import pytest
from app.core.dependencies import get_db
from app.main import app
from fastapi.testclient import TestClient


def _bar(listing_id, ts, close, volume=1000):
    return (ts, listing_id, close - 1, close + 2, close - 2, close, volume)


@pytest.fixture
def seeded(fresh_db, migrate):
    migrate(fresh_db)
    ids = {}
    with psycopg.connect(fresh_db) as conn:
        company_id = conn.execute(
            "INSERT INTO companies (name, isin) VALUES "
            "('Reliance Industries Limited', 'INE002A01018') RETURNING company_id"
        ).fetchone()[0]
        other_company = conn.execute(
            "INSERT INTO companies (name, isin) VALUES ('Tata Reliable Corp', 'INE000000001') "
            "RETURNING company_id"
        ).fetchone()[0]
        rows = [
            ("NSE", "RELIANCE", "equity", company_id, True),
            ("BSE", "RELIANCE", "equity", company_id, False),
            ("NSE", "RELI", "equity", None, True),
            ("NSE", "TATAREL", "equity", other_company, True),
            ("NSE", "NIFTY", "index", None, True),
        ]
        for ex, sym, kind, cid, active in rows:
            ids[(ex, sym)] = conn.execute(
                "INSERT INTO listings (exchange, symbol, kind, company_id, is_active) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING listing_id",
                (ex, sym, kind, cid, active),
            ).fetchone()[0]
        rel = ids[("NSE", "RELIANCE")]
        days = [f"2026-11-0{d}T00:00:00Z" for d in range(2, 7)]
        for i, ts in enumerate(days):
            conn.execute(
                "INSERT INTO ohlcv_1d (ts, listing_id, open, high, low, close, volume) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                _bar(rel, ts, 100.0 + i, 500 + i),
            )
        conn.execute(
            "INSERT INTO ohlcv_1w (ts, listing_id, open, high, low, close, volume) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            _bar(rel, "2026-11-02T00:00:00Z", 110.0),
        )
        for i, ts in enumerate(days[:3]):
            conn.execute(
                "INSERT INTO ta_daily (ts, listing_id, rsi_14, ema_200, calc_version) "
                "VALUES (%s,%s,%s,%s,'ta-1')",
                (ts, rel, 50.0 + i, None if i == 0 else 90.5),
            )
        sigs = [
            (rel, "HIGH_VOLUME_BUY", "2026-11-05T00:00:00Z", 2.0, "hvb-1"),
            (rel, "SENTIMENT", "2026-11-06T00:00:00Z", None, "s-1"),
            (ids[("NSE", "RELI")], "SENTIMENT", "2026-11-06T00:00:00Z", 1.5, "s-1"),
            (ids[("NSE", "TATAREL")], "SENTIMENT", "2026-11-06T00:00:00Z", 3.0, "s-1"),
            (ids[("NSE", "TATAREL")], "HIGH_VOLUME_BUY", "2026-11-01T00:00:00Z", 1.0, "hvb-1"),
        ]
        for lid, typ, as_of, strength, ver in sigs:
            conn.execute(
                "INSERT INTO signal (listing_id, signal_type, as_of, strength, meta, calc_version)"
                " VALUES (%s,%s,%s,%s,'{\"lookback\": 20}',%s)",
                (lid, typ, as_of, strength, ver),
            )
        conn.execute(
            "INSERT INTO swing_signals (listing_id, as_of, signal, entry, calc_version) "
            "VALUES (%s,'2026-11-05T00:00:00Z','BUY',99.5,'legacy-vinzo-core'), "
            "(%s,'2026-11-06T00:00:00Z','HOLD',null,'legacy-vinzo-core')",
            (rel, rel),
        )
    return fresh_db


@pytest.fixture
def client(seeded):
    conn = psycopg.connect(seeded)

    def _get_db():
        yield conn

    app.dependency_overrides[get_db] = _get_db
    try:
        yield TestClient(app)  # no `with`: the lifespan (and its pool) does not run
    finally:
        app.dependency_overrides.pop(get_db, None)
        conn.close()


def _syms(resp):
    return [(r["exchange"], r["symbol"]) for r in resp.json()]


def test_search_prefix_symbol_exact_first(client):
    r = client.get("/v1/instruments/listings", params={"q": "reli"})
    assert r.status_code == 200
    # RELI exact first, then symbol ascending; TATAREL matches by company substring "Reliable"
    assert _syms(r) == [("NSE", "RELI"), ("NSE", "RELIANCE"), ("NSE", "TATAREL")]
    first = r.json()[1]
    assert first["company_name"] == "Reliance Industries Limited"
    assert first["isin"] == "INE002A01018"
    assert first["kind"] == "equity"
    assert first["is_active"] is True
    assert set(first) == {
        "listing_id",
        "exchange",
        "symbol",
        "kind",
        "company_name",
        "isin",
        "is_active",
    }


def test_search_company_substring(client):
    r = client.get("/v1/instruments/listings", params={"q": "industries"})
    assert _syms(r) == [("NSE", "RELIANCE")]


def test_search_exchange_and_active_filters(client):
    r = client.get("/v1/instruments/listings", params={"q": "RELIANCE", "exchange": "bse"})
    assert _syms(r) == []  # BSE listing inactive, active defaults true
    r = client.get(
        "/v1/instruments/listings", params={"q": "RELIANCE", "exchange": "BSE", "active": "false"}
    )
    assert _syms(r) == [("BSE", "RELIANCE")]
    r = client.get("/v1/instruments/listings", params={"q": "RELIANCE", "active": "false"})
    assert _syms(r) == [("BSE", "RELIANCE"), ("NSE", "RELIANCE")]
    r = client.get("/v1/instruments/listings", params={"limit": 2})
    assert len(r.json()) == 2
    assert client.get("/v1/instruments/listings", params={"limit": 0}).status_code == 422
    assert client.get("/v1/instruments/listings", params={"exchange": "XYZ"}).status_code == 422


def test_listing_detail_latest_and_previous_close(client):
    r = client.get("/v1/instruments/listings/NSE/RELIANCE")
    assert r.status_code == 200
    body = r.json()
    assert body["latest"] == {
        "ts": "2026-11-06T00:00:00Z",
        "open": 103.0,
        "high": 106.0,
        "low": 102.0,
        "close": 104.0,
        "volume": 504,
    }
    assert body["previous_close"] == 103.0


def test_listing_detail_without_bars_and_404(client):
    body = client.get("/v1/instruments/listings/NSE/NIFTY").json()
    assert body["latest"] is None and body["previous_close"] is None
    assert body["company_name"] is None and body["isin"] is None
    r = client.get("/v1/instruments/listings/NSE/NOPE")
    assert r.status_code == 404
    assert r.json() == {"detail": "listing not found"}


def test_bars_newest_n_ascending(client):
    r = client.get("/v1/market-data/NSE/RELIANCE/bars", params={"limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert (body["exchange"], body["symbol"], body["timeframe"]) == ("NSE", "RELIANCE", "1d")
    assert [b["ts"] for b in body["bars"]] == [
        "2026-11-04T00:00:00Z",
        "2026-11-05T00:00:00Z",
        "2026-11-06T00:00:00Z",
    ]
    assert body["bars"][0]["close"] == 102.0


def test_bars_end_filter_inclusive_of_day(client):
    r = client.get("/v1/market-data/NSE/RELIANCE/bars", params={"end": "2026-11-04"})
    assert [b["ts"][:10] for b in r.json()["bars"]] == ["2026-11-02", "2026-11-03", "2026-11-04"]


def test_bars_weekly_and_empty_timeframe(client):
    r = client.get("/v1/market-data/NSE/RELIANCE/bars", params={"timeframe": "1w"})
    assert r.json()["timeframe"] == "1w"
    assert [b["close"] for b in r.json()["bars"]] == [110.0]
    r = client.get("/v1/market-data/NSE/RELIANCE/bars", params={"timeframe": "5m"})
    assert r.status_code == 200 and r.json()["bars"] == []


def test_bars_errors(client):
    assert (
        client.get("/v1/market-data/NSE/RELIANCE/bars", params={"timeframe": "2h"}).status_code
        == 422
    )
    assert (
        client.get("/v1/market-data/NSE/RELIANCE/bars", params={"limit": 5001}).status_code == 422
    )
    r = client.get("/v1/market-data/NSE/NOPE/bars")
    assert r.status_code == 404 and r.json() == {"detail": "listing not found"}


def test_indicators(client):
    r = client.get("/v1/market-data/NSE/RELIANCE/indicators", params={"limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["listing_id"] and body["symbol"] == "RELIANCE"
    rows = body["rows"]
    assert [x["ts"][:10] for x in rows] == ["2026-11-03", "2026-11-04"]
    assert rows[0]["rsi_14"] == 51.0 and rows[0]["ema_200"] == 90.5
    assert rows[0]["calc_version"] == "ta-1" and rows[0]["macd"] is None
    r = client.get("/v1/market-data/NSE/RELIANCE/indicators", params={"end": "2026-11-02"})
    assert [x["ema_200"] for x in r.json()["rows"]] == [None]
    assert client.get("/v1/market-data/NSE/NOPE/indicators").status_code == 404


def test_signal_types(client):
    r = client.get("/v1/signals/types")
    assert r.status_code == 200
    assert r.json() == [
        {
            "signal_type": "HIGH_VOLUME_BUY",
            "count": 2,
            "latest_as_of": "2026-11-05T00:00:00Z",
        },
        {"signal_type": "SENTIMENT", "count": 3, "latest_as_of": "2026-11-06T00:00:00Z"},
    ]


def test_signals_ordering_and_shape(client):
    r = client.get("/v1/signals")
    assert r.status_code == 200
    rows = r.json()
    # 11-06 SENTIMENT: strength desc nulls last -> TATAREL(3.0), RELI(1.5), RELIANCE(null)
    assert [(x["symbol"], x["signal_type"]) for x in rows] == [
        ("TATAREL", "SENTIMENT"),
        ("RELI", "SENTIMENT"),
        ("RELIANCE", "SENTIMENT"),
        ("RELIANCE", "HIGH_VOLUME_BUY"),
        ("TATAREL", "HIGH_VOLUME_BUY"),
    ]
    top = rows[0]
    assert top["company_name"] == "Tata Reliable Corp"
    assert top["meta"] == {"lookback": 20}
    assert top["strength"] == 3.0 and top["price"] is None
    assert top["calc_version"] == "s-1" and top["as_of"] == "2026-11-06T00:00:00Z"
    assert set(top) == {
        "id",
        "listing_id",
        "exchange",
        "symbol",
        "company_name",
        "signal_type",
        "as_of",
        "strength",
        "price",
        "volume",
        "avg_volume",
        "rationale",
        "meta",
        "calc_version",
    }


def test_signals_filters(client):
    r = client.get("/v1/signals", params={"signal_type": "HIGH_VOLUME_BUY"})
    assert len(r.json()) == 2
    r = client.get("/v1/signals", params={"exchange": "nse", "symbol": "RELIANCE"})
    assert {x["symbol"] for x in r.json()} == {"RELIANCE"} and len(r.json()) == 2
    r = client.get("/v1/signals", params={"exchange": "BSE"})
    assert r.json() == []
    r = client.get("/v1/signals", params={"since": "2026-11-05"})
    assert len(r.json()) == 4
    r = client.get("/v1/signals", params={"limit": 1})
    assert len(r.json()) == 1
    assert client.get("/v1/signals", params={"limit": 501}).status_code == 422


def test_swing(client):
    r = client.get("/v1/signals/swing")
    assert r.status_code == 200
    rows = r.json()
    assert [x["signal"] for x in rows] == ["HOLD", "BUY"]
    assert rows[1]["entry"] == 99.5 and rows[1]["stop_loss"] is None
    assert rows[0]["symbol"] == "RELIANCE" and rows[0]["calc_version"] == "legacy-vinzo-core"
    assert rows[0]["as_of"] == "2026-11-06T00:00:00Z"
    assert len(client.get("/v1/signals/swing", params={"exchange": "NSE", "limit": 1}).json()) == 1
    assert client.get("/v1/signals/swing", params={"exchange": "BSE"}).json() == []


def _add_provider_symbols(db_url, symbols):
    with psycopg.connect(db_url) as conn:
        for exchange, symbol in symbols:
            conn.execute(
                "INSERT INTO provider_symbols (provider, provider_symbol, listing_id) "
                "SELECT 'yahoo', %s, listing_id FROM listings WHERE exchange = %s AND symbol = %s",
                (f"{symbol}.{exchange}", exchange, symbol),
            )


def test_overview_lists_only_ingested_listings_with_sparkline(client, seeded):
    _add_provider_symbols(seeded, [("NSE", "RELIANCE"), ("NSE", "TATAREL")])
    r = client.get("/v1/market-data/overview", params={"points": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == "2026-11-06T00:00:00Z"
    assert body["points"] == 3
    stocks = body["stocks"]
    # NIFTY / RELI / BSE RELIANCE have no provider symbol, so they were never ingested
    assert [(s["exchange"], s["symbol"]) for s in stocks] == [
        ("NSE", "RELIANCE"),
        ("NSE", "TATAREL"),
    ]
    rel, tata = stocks
    assert rel["closes"] == [102.0, 103.0, 104.0]
    assert rel["close"] == 104.0 and rel["previous_close"] == 103.0
    assert rel["change_pct"] == pytest.approx(100 * (104.0 - 103.0) / 103.0)
    assert rel["volume"] == 504
    assert rel["latest_ts"] == "2026-11-06T00:00:00Z"
    assert rel["company_name"] == "Reliance Industries Limited"
    assert set(rel) == {
        "listing_id",
        "exchange",
        "symbol",
        "kind",
        "company_name",
        "is_active",
        "latest_ts",
        "close",
        "previous_close",
        "change_pct",
        "volume",
        "closes",
    }
    # Ingested but no bars in the window: still listed, with empty price fields
    assert tata["closes"] == [] and tata["close"] is None and tata["change_pct"] is None
    assert tata["latest_ts"] is None and tata["volume"] is None


def test_overview_filters_and_validation(client, seeded):
    _add_provider_symbols(seeded, [("NSE", "RELIANCE"), ("BSE", "RELIANCE")])
    r = client.get("/v1/market-data/overview", params={"exchange": "bse"})
    assert [(s["exchange"], s["symbol"]) for s in r.json()["stocks"]] == [("BSE", "RELIANCE")]
    assert r.json()["as_of"] is None  # the BSE listing has no bars
    r = client.get("/v1/market-data/overview")
    assert r.json()["points"] == 60
    assert len(r.json()["stocks"][1]["closes"]) == 5  # NSE RELIANCE: all 5 seeded bars
    for bad in ({"points": 1}, {"points": 251}, {"exchange": "XYZ"}):
        assert client.get("/v1/market-data/overview", params=bad).status_code == 422


# ---- Ingestion selection (admin) ----

SELECTION = "/v1/instruments/selection"


def _row(resp, symbol):
    return next(r for r in resp.json()["rows"] if r["symbol"] == symbol)


def test_selection_lists_symbols_with_per_exchange_state(client):
    r = client.get(SELECTION)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["selected"] == {"NSE": 4, "BSE": 0}
    assert [x["symbol"] for x in body["rows"]] == ["NIFTY", "RELI", "RELIANCE", "TATAREL"]
    rel = _row(r, "RELIANCE")
    assert rel["company_name"] == "Reliance Industries Limited" and rel["kind"] == "equity"
    assert rel["nse"]["is_active"] is True and rel["nse"]["provider_symbol"] is None
    assert rel["nse"]["last_bar"] == "2026-11-06T00:00:00Z"
    assert rel["bse"]["is_active"] is False and rel["bse"]["last_bar"] is None
    assert _row(r, "TATAREL")["bse"] is None
    assert set(rel) == {"symbol", "company_name", "isin", "kind", "nse", "bse"}
    assert set(rel["nse"]) == {"listing_id", "is_active", "provider_symbol", "last_bar"}


def test_selection_filters_and_paging(client):
    names = lambda r: [x["symbol"] for x in r.json()["rows"]]  # noqa: E731
    assert names(client.get(SELECTION, params={"q": "tata"})) == ["TATAREL"]
    assert names(client.get(SELECTION, params={"q": "industries"})) == ["RELIANCE"]
    r = client.get(SELECTION, params={"limit": 2, "offset": 1})
    assert names(r) == ["RELI", "RELIANCE"] and r.json()["total"] == 4
    assert client.get(SELECTION, params={"status": "unselected"}).json()["rows"] == []
    assert client.get(SELECTION, params={"status": "bogus"}).status_code == 422
    assert client.get(SELECTION, params={"limit": 201}).status_code == 422


def test_selection_deselect_and_reselect_creates_provider_symbol(client):
    r = client.put(f"{SELECTION}/NSE/RELI", json={"selected": False})
    assert r.status_code == 200
    assert r.json()["nse"]["is_active"] is False
    r = client.get(SELECTION, params={"status": "unselected"})
    assert [x["symbol"] for x in r.json()["rows"]] == ["RELI"]
    assert r.json()["selected"] == {"NSE": 3, "BSE": 0}
    r = client.put(f"{SELECTION}/nse/RELI", json={"selected": True})
    assert r.json()["nse"] == {**r.json()["nse"], "is_active": True, "provider_symbol": "RELI.NS"}


def test_selection_bse_existing_and_created_listing(client):
    r = client.put(f"{SELECTION}/BSE/RELIANCE", json={"selected": True})
    assert r.status_code == 200
    assert r.json()["bse"]["is_active"] is True
    assert r.json()["bse"]["provider_symbol"] == "RELIANCE.BO"
    # TATAREL has no BSE listing yet: selecting BSE creates one for the same company
    r = client.put(f"{SELECTION}/BSE/TATAREL", json={"selected": True})
    assert r.status_code == 200
    bse = r.json()["bse"]
    assert bse["is_active"] is True and bse["provider_symbol"] == "TATAREL.BO"
    assert client.get("/v1/instruments/listings/BSE/TATAREL").json()["company_name"] == (
        "Tata Reliable Corp"
    )
    assert client.get(SELECTION).json()["selected"] == {"NSE": 4, "BSE": 2}
    # Deselecting a BSE listing that does not exist is a no-op
    r = client.put(f"{SELECTION}/BSE/RELI", json={"selected": False})
    assert r.status_code == 200 and r.json()["bse"] is None


def test_selection_errors(client):
    r = client.put(f"{SELECTION}/NSE/NOPE", json={"selected": True})
    assert r.status_code == 404 and r.json() == {"detail": "symbol not found"}
    # No company to attach a BSE listing to (index / unlinked listing)
    for symbol in ("NIFTY", "RELI"):
        r = client.put(f"{SELECTION}/BSE/{symbol}", json={"selected": True})
        assert r.status_code == 409
    assert client.put(f"{SELECTION}/XYZ/RELI", json={"selected": True}).status_code == 422
    assert client.put(f"{SELECTION}/NSE/RELI", json={}).status_code == 422
