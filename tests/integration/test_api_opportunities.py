"""API tests for the opportunities module against a throwaway migrated database."""

import json

import psycopg
import pytest
from app.core.dependencies import get_db
from app.main import app
from fastapi.testclient import TestClient

OLD, NEW = "2026-11-12T00:00:00Z", "2026-11-13T00:00:00Z"


def _pick(conn, listing_id, horizon, as_of, *, direction="BUY", status="actionable", score=80):
    return conn.execute(
        """INSERT INTO opportunity (listing_id, horizon, as_of, direction, status, score,
               confidence, price, entry_low, entry_high, stop_loss, targets, risk_reward,
               holding_period, max_sessions, supports, resistances, reasons, factors, risks,
               invalidation, regime, inputs, calc_version)
           VALUES (%s, %s, %s, %s, %s, %s, 'medium', 100, 99, 101, 95, '{110,115}', 2.0,
               '5–20 trading sessions', 20, '{96}', '{110}', %s, %s, '["No events calendar"]',
               '["Daily close below 95"]', %s, '{"close": 100}', 'opp-test')
           RETURNING id""",
        (
            listing_id,
            horizon,
            as_of,
            direction,
            status,
            score,
            json.dumps(["Breakout above the 20-day high"]),
            json.dumps([{"group": "trend", "score": 0.8, "reason": "Close above the 21-day EMA"}]),
            json.dumps({"score": 0.5, "label": "bullish", "notes": ["NIFTY above its 50-day EMA"]}),
        ),
    ).fetchone()[0]


def _outcome(conn, pick_id, status, ret):
    conn.execute(
        "INSERT INTO opportunity_outcome (opportunity_id, status, entry_price, exit_price, "
        "return_pct, sessions_held, calc_version) VALUES (%s, %s, 100, 100, %s, 3, 'o-test')",
        (pick_id, status, ret),
    )


@pytest.fixture
def seeded(fresh_db, migrate):
    migrate(fresh_db)
    ids = {}
    with psycopg.connect(fresh_db) as conn:
        company = conn.execute(
            "INSERT INTO companies (name, isin) VALUES ('Alpha Ltd', 'INE0000A0001') "
            "RETURNING company_id"
        ).fetchone()[0]
        listings = {}
        for symbol in ("ALPHA", "BETA", "GAMMA"):
            listings[symbol] = conn.execute(
                "INSERT INTO listings (exchange, symbol, kind, company_id, is_active) "
                "VALUES ('NSE', %s, 'equity', %s, true) RETURNING listing_id",
                (symbol, company if symbol == "ALPHA" else None),
            ).fetchone()[0]
        a, b, g = listings["ALPHA"], listings["BETA"], listings["GAMMA"]
        # Today's picks
        ids["swing_watch"] = _pick(conn, b, "swing", NEW, status="watch", score=90)
        ids["swing_top"] = _pick(conn, a, "swing", NEW, score=80)
        ids["swing_sell"] = _pick(conn, g, "swing", NEW, direction="SELL", score=76)
        conn.execute(
            "UPDATE opportunity SET setups = %s WHERE id = %s",
            (
                json.dumps([{"key": "breakout", "variant": "", "reason": "Closed below"}]),
                ids["swing_sell"],
            ),
        )
        ids["long"] = _pick(conn, a, "long_term", NEW, score=88)
        # Yesterday's picks: closed, for the track record
        for listing, status, ret, score in (
            (a, "target_hit", 10.0, 80),
            (b, "stopped", -5.0, 72),
            (g, "expired", 1.0, 90),
            (a, "not_triggered", None, 60),
        ):
            pid = _pick(
                conn, listing, "swing" if listing != a or ret else "next_session", OLD, score=score
            )
            _outcome(conn, pid, status, ret)
        _pick(conn, b, "long_term", OLD, score=70)  # still open
    return fresh_db, ids


@pytest.fixture
def client(seeded):
    url, _ = seeded
    conn = psycopg.connect(url)

    def _get_db():
        yield conn

    app.dependency_overrides[get_db] = _get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        conn.close()


def test_current_picks_grouped_by_horizon_and_ranked(client, seeded):
    _, ids = seeded
    r = client.get("/v1/opportunities")
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == NEW
    assert body["regime"]["label"] == "bullish"
    assert "end-of-day" in body["data_note"]
    swing = body["horizons"]["swing"]
    # Actionable first, then score: the watch pick with 90 ranks after both actionable picks.
    assert [x["id"] for x in swing] == [ids["swing_top"], ids["swing_sell"], ids["swing_watch"]]
    top = swing[0]
    assert top["symbol"] == "ALPHA" and top["exchange"] == "NSE"
    assert top["company_name"] == "Alpha Ltd"
    assert top["targets"] == [110.0, 115.0] and top["supports"] == [96.0]
    assert top["factors"][0]["group"] == "trend"
    assert "inputs" not in top
    assert top["setups"] == [] and swing[1]["setups"][0]["key"] == "breakout"
    assert [x["id"] for x in body["horizons"]["long_term"]] == [ids["long"]]
    assert body["horizons"]["next_session"] == []


def test_pick_detail_has_inputs_and_outcome(client, seeded):
    _, ids = seeded
    body = client.get(f"/v1/opportunities/{ids['swing_top']}").json()
    assert body["inputs"] == {"close": 100} and body["outcome"] is None
    assert body["calc_version"] == "opp-test"
    assert client.get("/v1/opportunities/999999").status_code == 404


def test_performance_by_horizon_and_score_band(client):
    r = client.get("/v1/opportunities/performance", params={"status": "all"})
    assert r.status_code == 200
    assert r.json()["status"] == "all"
    swing = r.json()["horizons"]["swing"]
    assert swing["picks"] == 6 and swing["open"] == 3  # today's 3 are still open
    assert swing["closed"] == {"target_hit": 1, "stopped": 1, "expired": 1, "not_triggered": 0}
    # Hit rate over triggered picks: 1 of 3; average return (10 - 5 + 1) / 3
    assert swing["hit_rate"] == pytest.approx(1 / 3)
    assert swing["avg_return_pct"] == pytest.approx(2.0)
    bands = {b["band"]: b for b in swing["by_score"]}
    assert bands["85-100"]["triggered"] == 1 and bands["70-84"]["triggered"] == 2
    ns = r.json()["horizons"]["next_session"]
    assert ns["closed"]["not_triggered"] == 1 and ns["hit_rate"] is None
    recent = r.json()["recent"]
    assert {x["status"] for x in recent} == {"target_hit", "stopped", "expired", "not_triggered"}
    assert recent[0]["symbol"] in {"ALPHA", "BETA", "GAMMA"}


def test_performance_defaults_to_actionable_picks(client):
    body = client.get("/v1/opportunities/performance").json()
    assert body["status"] == "actionable"
    assert body["horizons"]["swing"]["picks"] == 5  # today's watch pick is excluded
    watch = client.get("/v1/opportunities/performance", params={"status": "watch"}).json()
    assert watch["horizons"]["swing"]["picks"] == 1 and watch["recent"] == []
    assert client.get("/v1/opportunities/performance", params={"status": "x"}).status_code == 422


def test_repeats_of_an_open_pick_are_counted_once(client, seeded):
    url, _ = seeded
    with psycopg.connect(url) as conn:
        lid = conn.execute("SELECT listing_id FROM listings WHERE symbol = 'GAMMA'").fetchone()[0]
        days = ["2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z", "2026-11-04T00:00:00Z"]
        ids = [_pick(conn, lid, "long_term", d, direction="SELL") for d in days]
        # The first pick stayed open until 11-04, so the 11-03 pick repeats it; the 11-04 pick
        # starts on the day the first one closed, which still overlaps, so it repeats too.
        conn.execute(
            "INSERT INTO opportunity_outcome (opportunity_id, status, exit_at, return_pct, "
            "calc_version) VALUES (%s, 'stopped', '2026-11-04T00:00:00Z', -5, 't'), "
            "(%s, 'stopped', '2026-11-04T00:00:00Z', -5, 't'), "
            "(%s, 'stopped', '2026-11-05T00:00:00Z', -5, 't')",
            ids,
        )
    lt = client.get("/v1/opportunities/performance").json()["horizons"]["long_term"]
    assert lt["closed"]["stopped"] == 1


def test_empty_database(fresh_db, migrate):
    migrate(fresh_db)
    conn = psycopg.connect(fresh_db)

    def _get_db():
        yield conn

    app.dependency_overrides[get_db] = _get_db
    try:
        body = TestClient(app).get("/v1/opportunities").json()
        assert body["as_of"] is None
        assert body["horizons"] == {"next_session": [], "swing": [], "long_term": []}
    finally:
        app.dependency_overrides.pop(get_db, None)
        conn.close()
