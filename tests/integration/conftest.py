"""Shared integration-test fixtures: throwaway Postgres databases plus a dbmate-style migrator."""

import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "database" / "postgres" / "migrations"
PENDING_DIR = ROOT / "database" / "postgres" / "pending"

_UP_RE = re.compile(r"^--\s*migrate:up\b(.*)$", re.MULTILINE)
_DOWN_RE = re.compile(r"^--\s*migrate:down\b.*$", re.MULTILINE)


def _base_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export ") :]
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("DATABASE_URL not set in environment or repo .env")


def _url_with_db(url: str, dbname: str) -> str:
    return make_conninfo(url, dbname=dbname)


def _split_up(text: str, name: str) -> tuple[str, bool]:
    """Return (up_sql, transactional) for a dbmate migration file."""
    up = _UP_RE.search(text)
    if up is None:
        raise ValueError(f"{name}: no '-- migrate:up' marker")
    transactional = "transaction:false" not in up.group(1)
    body = text[up.end() :]
    down = _DOWN_RE.search(body)
    if down is not None:
        body = body[: down.start()]
    return body, transactional


def _index_of(files: list[Path], prefix: str, arg: str) -> int:
    idx = next((i for i, p in enumerate(files) if p.name.startswith(prefix)), None)
    if idx is None:
        raise ValueError(f"no migration file matches {arg}={prefix!r}")
    return idx


def apply_migrations(
    url: str,
    *,
    after: str | None = None,
    until: str | None = None,
    include_pending: bool = False,
) -> list[str]:
    """Apply `-- migrate:up` sections in filename order; return applied versions.

    `after` skips every file up to and including the one matching that prefix; `until` stops
    after the file matching that prefix. They combine, e.g. after="…07", until="…08" applies 08.
    """
    files = list(MIGRATIONS_DIR.glob("*.sql"))
    if include_pending and PENDING_DIR.is_dir():
        files += list(PENDING_DIR.glob("*.sql"))
    files.sort(key=lambda p: p.name)
    start = 0 if after is None else _index_of(files, after, "after") + 1
    end = len(files) if until is None else _index_of(files, until, "until") + 1
    files = files[start:end]

    applied: list[str] = []
    for path in files:
        body, transactional = _split_up(path.read_text(), path.name)
        if transactional:
            with psycopg.connect(url) as conn:  # commits on clean exit
                conn.execute(body)
        else:
            with psycopg.connect(url, autocommit=True) as conn:
                conn.execute(body)
        applied.append(path.name.split("_", 1)[0])
    return applied


@pytest.fixture
def migrate():
    return apply_migrations


@pytest.fixture
def fresh_db(request):
    base = _base_url()
    admin_url = _url_with_db(base, "postgres")
    name = f"vynzo_test_{uuid.uuid4().hex[:8]}"
    assert conninfo_to_dict(base).get("dbname") != name
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield _url_with_db(base, name)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


# Legacy fixture (baseline shape, keyed by symbol + exchange). Values are deliberately
# non-round so copy tests can compare floats with exact equality. Ids are explicit and
# the sequences are left behind them, so a missing setval after a copy shows up.
# ta_daily row 2 has NULL ema_200 / ema200_slope_20 / ret_126 (short history), so
# value comparisons must use IS NOT DISTINCT FROM.
LEGACY_SEED_SQL = """
INSERT INTO ohlcv_1d (ts, symbol, exchange, open, high, low, close, volume) VALUES
  ('2026-11-04 00:00:00+05:30', 'RELIANCE', 'NSE',
   2489.517203841, 2512.904417736, 2480.066158492, 2501.123456789, 7340219),
  ('2026-11-05 00:00:00+05:30', 'RELIANCE', 'NSE',
   2501.987654321, 2533.314159265, 2497.271828182, 2528.456789012, 9123457),
  ('2026-11-06 00:00:00+05:30', 'RELIANCE', 'NSE',
   2528.111111119, 2541.602214076, 2510.302585093, 2515.707106781, 6018833),
  ('2026-11-06 00:00:00+05:30', 'NIFTY', 'NSE',
   24301.418, 24412.663527, 24255.170031, 24398.9171819, 0);

INSERT INTO ohlcv_1w (ts, symbol, exchange, open, high, low, close, volume) VALUES
  ('2026-11-02 00:00:00+05:30', 'INFY', 'BSE',
   1702.257, 1745.393, 1698.0123456, 1739.8765432, 1287653);

INSERT INTO ta_daily (
  ts, symbol, exchange, rsi_14, ema_9, ema_21, ema_50, ema_200, macd, macd_signal, macd_hist,
  atr_14, vwap, adx_14, plus_di_14, minus_di_14, rvol_20, donchian_high_20, donchian_low_20,
  donchian_high_55, bb_width, obv, ema200_slope_20, extension_atr, ret_126
) VALUES
  ('2026-11-05 00:00:00+05:30', 'RELIANCE', 'NSE', 61.73205080756888, 2510.4142135623,
   2498.7320508075, 2470.2360679775, 2390.9442719099, 11.180339887498949, 9.486832980505138,
   0.30000000000000004, 34.64101615137755, 2519.2915026221, 27.386127875258307,
   24.49489742783178, 15.811388300841896, 1.4142135623730951, 2541.602214076,
   2441.0284927, 2589.9999999999995, 0.04472135954999579, 183456789.25, 0.7071067811865476,
   1.7320508075688772, 0.12247448713915889),
  ('2026-11-06 00:00:00+05:30', 'RELIANCE', 'NSE', 55.90169943749474, 2511.8033988749,
   2500.4721359549, 2471.6227766016, NULL, 10.954451150103322, 9.797958971132712,
   1.1564921789712100, 33.166247903554, 2520.6457513110, 26.457513110645905,
   23.664319132398465, 16.583123951777, 0.9486832980505138, 2541.602214076,
   2441.0284927, 2589.9999999999995, 0.04358898943540674, 177438556.75, NULL,
   1.6583123951777, NULL);

INSERT INTO signal (
  id, created_at, as_of, symbol, exchange, signal_type, strength, price, volume, avg_volume,
  rationale, meta
) VALUES
  (4217, '2026-11-05 18:31:07.123456+05:30', '2026-11-05 00:00:00+05:30', 'RELIANCE', 'NSE',
   'HIGH_VOLUME_BUY', 2.3719473820751, 2528.456789012, 9123457, 3846421.85,
   'Volume 2.37x 20-day average on an up day',
   '{"lookback": 20, "multiplier": 2.0, "ratio": 2.3719473820751}');

INSERT INTO swing_signals (
  id, created_at, as_of, symbol, exchange, signal, entry, stop_loss, target_1, target_2,
  risk_reward, rationale, meta
) VALUES
  (913, '2026-11-06 18:45:00.654321+05:30', '2026-11-06 00:00:00+05:30', 'RELIANCE', 'NSE',
   'BUY', 2515.707106781, 2462.1803398875, 2583.8541019662, 2636.0820393249,
   1.2716417910447761, 'Breakout above 20-day Donchian high', '{"score": 7.25}');

INSERT INTO ingest_runs (
  id, started_at, finished_at, symbol, exchange, timeframe, rows_upserted, gaps_found, status,
  notes
) VALUES
  (1661, '2026-11-06 16:30:01.000123+05:30', '2026-11-06 16:30:04.987654+05:30', 'RELIANCE',
   'NSE', '1d', 3, 1, 'ok', 'legacy fixture run');

INSERT INTO ohlcv_gaps (
  id, detected_at, symbol, exchange, timeframe, gap_start, gap_end, resolved
) VALUES
  (1877, '2026-11-06 16:30:04.5+05:30', 'RELIANCE', 'NSE', '1d',
   '2026-11-01 00:00:00+05:30', '2026-11-03 00:00:00+05:30', false);

-- Added in Task 3: 1mo and intraday bars, plus pairs that exist in only one legacy table.
INSERT INTO ohlcv_1mo (ts, symbol, exchange, open, high, low, close, volume) VALUES
  ('2026-10-01 00:00:00+05:30', 'RELIANCE', 'NSE',
   2398.765432109, 2577.123456789, 2371.000000001, 2489.517203841, 187654321);

-- Intraday timestamps are relative to now() so the 365/730/1825-day retention jobs on the
-- intraday hypertables never drop seeded rows.
INSERT INTO ohlcv_5m (ts, symbol, exchange, open, high, low, close, volume) VALUES
  (date_trunc('minute', now()) - interval '2 days 3 hours', 'RELIANCE', 'NSE',
   2516.05, 2517.4142135623731, 2515.1010101, 2516.9876543210987, 48213),
  (date_trunc('minute', now()) - interval '2 days 2 hours 55 minutes', 'RELIANCE', 'NSE',
   2516.9876543210987, 2519.000000000001, 2516.3, 2518.7071067811865, 51877),
  (date_trunc('minute', now()) - interval '1 day 4 hours', 'TATAMOTORS', 'NSE',
   712.3333333333334, 714.1, 711.9000000000001, 713.6666666666666, 120931);

INSERT INTO ohlcv_15m (ts, symbol, exchange, open, high, low, close, volume) VALUES
  (date_trunc('minute', now()) - interval '3 days 1 hour', 'RELIANCE', 'NSE',
   2509.4, 2512.7320508075689, 2507.2360679774998, 2511.1, 152003);

INSERT INTO ohlcv_75m (ts, symbol, exchange, open, high, low, close, volume) VALUES
  (date_trunc('minute', now()) - interval '5 days 2 hours', 'RELIANCE', 'NSE',
   2490.000000000001, 2503.3, 2488.1, 2501.6180339887499, 1043877);

INSERT INTO signal (
  id, created_at, as_of, symbol, exchange, signal_type, strength, price, volume, avg_volume,
  rationale, meta
) VALUES
  (4302, '2026-11-06 19:02:11.000001+05:30', '2026-11-06 00:00:00+05:30', 'HDFCBANK', 'NSE',
   'SENTIMENT', -0.41273, NULL, NULL, NULL, NULL,
   '{"source": "news", "headlines": 3, "scores": [-0.5, -0.25, -0.4782]}');

INSERT INTO ingest_runs (
  id, started_at, finished_at, symbol, exchange, timeframe, rows_upserted, gaps_found, status,
  notes
) VALUES
  (1662, '2026-11-06 16:31:00.5+05:30', NULL, 'INFY', 'BSE', '1w', 0, 0, 'running', NULL);
"""


def seed_legacy_data(url: str) -> None:
    """Apply the baseline migrations (idempotent) and insert the legacy fixture."""
    apply_migrations(url, until="20261108000005")
    with psycopg.connect(url) as conn:
        conn.execute(LEGACY_SEED_SQL)


@pytest.fixture
def seed_legacy():
    """Return `seed(url)`: baseline schema plus the legacy fixture.

    RELIANCE/NSE: 3 ohlcv_1d bars, 1 ohlcv_1mo, 2 ohlcv_5m, 1 ohlcv_15m, 1 ohlcv_75m bar,
    2 ta_daily rows, 1 HIGH_VOLUME_BUY signal (id 4217), 1 swing_signals row (id 913),
    1 ingest_runs row (id 1661), 1 ohlcv_gaps row (id 1877).
    INFY/BSE: 1 ohlcv_1w bar, 1 ingest_runs row (id 1662, NULL finished_at/notes).
    NIFTY/NSE: 1 ohlcv_1d bar. TATAMOTORS/NSE: only 1 ohlcv_5m bar.
    HDFCBANK/NSE: only 1 SENTIMENT signal (id 4302, NULL price/volume/avg_volume/rationale).
    5 listings result. Call it before applying 06+.
    """
    return seed_legacy_data
