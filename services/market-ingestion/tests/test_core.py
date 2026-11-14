import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from market_ingestion.normalization.bars import Bar, normalize
from market_ingestion.providers.vendor.yahoo import YahooProvider
from market_ingestion.recovery.gaps import detect_gaps
from market_ingestion.sessions import expected_latest_session, last_complete_session
from market_ingestion.validation.bars import validate_bars

IST = ZoneInfo("Asia/Kolkata")
FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_reliance_1d.json"


def frame_from_fixture() -> pd.DataFrame:
    data = json.loads(FIXTURE.read_text())
    idx = pd.to_datetime(data.pop("index"), utc=True)
    df = pd.DataFrame(data, index=idx, dtype="float64")
    df.index.name = "Date"
    return df


def _records():
    p = YahooProvider(download=lambda *a, **k: frame_from_fixture())
    return p.fetch_bars("RELIANCE.NS", "1d", None, date(2026, 11, 6))


def test_yahoo_parses_fixture():
    recs = _records()
    assert len(recs) == 10
    assert all(r.bar_ts.tzinfo == UTC for r in recs)
    assert all(set(r.payload) == {"Open", "High", "Low", "Close", "Volume"} for r in recs)
    assert all(r.provider == "yahoo" and r.timeframe == "1d" for r in recs)
    assert isinstance(recs[0].payload["Volume"], int)
    json.dumps(recs[0].payload)


def test_yahoo_empty_frame():
    p = YahooProvider(download=lambda *a, **k: pd.DataFrame())
    assert p.fetch_bars("RELIANCE.NS", "1d", None, date(2026, 11, 6)) == []


def test_yahoo_rejects_aggregation_only_timeframe():
    p = YahooProvider(download=lambda *a, **k: pd.DataFrame())
    with pytest.raises(ValueError):
        p.fetch_bars("RELIANCE.NS", "75m", None, date(2026, 11, 6))


def test_yahoo_download_kwargs():
    seen = {}

    def dl(ticker, **kw):
        seen["t"], seen["kw"] = ticker, kw
        return pd.DataFrame()

    p = YahooProvider(download=dl)
    p.fetch_bars("^NSEI", "1d", None, date(2026, 11, 6))
    assert seen["t"] == "^NSEI" and seen["kw"]["period"] == "max"
    p.fetch_bars("^NSEI", "15m", None, date(2026, 11, 6))
    assert seen["kw"]["period"] == "60d"
    p.fetch_bars("^NSEI", "1d", date(2026, 11, 1), date(2026, 11, 6))
    assert seen["kw"]["start"] == "2026-11-01" and seen["kw"]["end"] == "2026-11-07"


def test_normalize_skips_nan():
    bars = normalize(_records(), listing_id=7)
    assert len(bars) == 9
    assert all(b.listing_id == 7 and isinstance(b.volume, int) for b in bars)


def _bar(ts, **kw):
    d = dict(listing_id=1, ts=ts, open=10.0, high=12.0, low=9.0, close=11.0, volume=100)
    d.update(kw)
    return Bar(**d)


def test_validate_drops_bad_and_future():
    bars = normalize(_records(), listing_id=1)
    out = validate_bars(bars, date(2026, 11, 6))
    assert len(out) == 8  # high<low bar dropped
    assert all(b.high >= b.low for b in out)

    yesterday = date(2026, 11, 10)
    today_1000 = datetime(2026, 11, 11, 10, 0, tzinfo=IST).astimezone(UTC)
    today_midnight_ist = datetime(2026, 11, 10, 18, 30, tzinfo=UTC)
    ok = _bar(datetime(2026, 11, 9, 18, 30, tzinfo=UTC))
    kept = validate_bars([ok, _bar(today_1000), _bar(today_midnight_ist)], yesterday)
    assert kept == [ok]

    ts = datetime(2026, 11, 9, 18, 30, tzinfo=UTC)
    dup = validate_bars([_bar(ts, close=10.5), _bar(ts, close=11.5)], yesterday)
    assert len(dup) == 1 and dup[0].close == 11.5


def test_gaps_daily_skips_weekend():
    fri = datetime(2026, 11, 6, tzinfo=UTC)
    mon = datetime(2026, 11, 9, tzinfo=UTC)
    assert detect_gaps([fri, mon], "1d") == []
    later = mon + timedelta(days=10)
    assert detect_gaps([mon, later], "1d") == [(mon, later)]


def test_last_complete_session():
    wed_1559 = datetime(2026, 11, 11, 15, 59, tzinfo=IST)
    wed_1600 = datetime(2026, 11, 11, 16, 0, tzinfo=IST)
    assert last_complete_session(wed_1559) == date(2026, 11, 10)
    assert last_complete_session(wed_1600) == date(2026, 11, 11)


def test_expected_latest_session_weekend():
    sun = datetime(2026, 11, 8, 12, 0, tzinfo=IST)
    assert expected_latest_session(sun) == date(2026, 11, 6)


def _frame(index):
    return pd.DataFrame(
        {"Open": 10.0, "High": 12.0, "Low": 9.0, "Close": 11.0, "Volume": 100.0},
        index=index,
    )


def _fetch(index, start=None):
    p = YahooProvider(download=lambda *a, **k: _frame(index))
    return p.fetch_bars("RELIANCE.NS", "1d", start, date(2026, 11, 6))


def test_daily_ts_utc_midnight_from_aware_ist_index():
    idx = pd.DatetimeIndex(["2026-11-05", "2026-11-06"], tz="Asia/Kolkata")
    recs = _fetch(idx)
    assert [r.bar_ts for r in recs] == [
        datetime(2026, 11, 5, tzinfo=UTC),
        datetime(2026, 11, 6, tzinfo=UTC),
    ]


def test_daily_ts_utc_midnight_from_naive_index():
    idx = pd.DatetimeIndex(["2026-11-05", "2026-11-06"])
    recs = _fetch(idx)
    assert [r.bar_ts for r in recs] == [
        datetime(2026, 11, 5, tzinfo=UTC),
        datetime(2026, 11, 6, tzinfo=UTC),
    ]


def test_start_day_bar_kept_with_aware_index():
    idx = pd.DatetimeIndex(["2026-11-02", "2026-11-03"], tz="Asia/Kolkata")
    recs = _fetch(idx, start=date(2026, 11, 2))
    assert recs[0].bar_ts == datetime(2026, 11, 2, tzinfo=UTC)
    assert len(recs) == 2


def test_validation_treats_utc_midnight_bar_as_that_date():
    b = _bar(datetime(2026, 11, 10, tzinfo=UTC))
    assert validate_bars([b], date(2026, 11, 10)) == [b]
    assert validate_bars([b], date(2026, 11, 9)) == []
