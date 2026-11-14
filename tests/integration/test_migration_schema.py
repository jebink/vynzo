"""Migrations 06 (instrument identity) and 07 (park legacy, create listing-keyed tables)."""

from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_07 = (
    ROOT
    / "database"
    / "postgres"
    / "migrations"
    / "20261111000007_park_legacy_and_create_tables.sql"
)
MIGRATION_06 = (
    ROOT / "database" / "postgres" / "migrations" / "20261111000006_instrument_identity.sql"
)

LEGACY_TABLES = [
    "ohlcv_daily",
    "ohlcv_1m",
    "ohlcv_5m",
    "ohlcv_15m",
    "ohlcv_75m",
    "ohlcv_1d",
    "ohlcv_1w",
    "ohlcv_1mo",
    "ta_daily",
    "ingest_runs",
    "ohlcv_gaps",
    "signal",
    "swing_signals",
]
LEGACY_SEQUENCES = [
    "ingest_runs_id_seq",
    "ohlcv_gaps_id_seq",
    "signal_id_seq",
    "swing_signals_id_seq",
]
BAR_TABLES = ["ohlcv_1m", "ohlcv_5m", "ohlcv_15m", "ohlcv_75m", "ohlcv_1d", "ohlcv_1w", "ohlcv_1mo"]
LISTING_KEYED = [*BAR_TABLES, "ta_daily", "ingest_runs", "ohlcv_gaps", "signal", "swing_signals"]


def _down_sql(path: Path) -> str:
    _, down = path.read_text().split("-- migrate:down", 1)
    return down


@pytest.fixture
def migrated(fresh_db, migrate, seed_legacy):
    seed_legacy(fresh_db)
    migrate(fresh_db, until="20261111000007")
    return fresh_db


def _rows(url: str, query: str, params=None) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(query, params).fetchall()


def _scalar(url: str, query: str, params=None):
    return _rows(url, query, params)[0][0]


def test_listings_created_from_legacy(migrated):
    rows = _rows(
        migrated,
        "select exchange, symbol, kind, is_active, company_id from listings order by symbol",
    )
    assert rows == [
        ("NSE", "HDFCBANK", "equity", True, None),
        ("BSE", "INFY", "equity", True, None),
        ("NSE", "NIFTY", "index", True, None),
        ("NSE", "RELIANCE", "equity", True, None),
        ("NSE", "TATAMOTORS", "equity", True, None),
    ]


def test_provider_symbols(migrated):
    rows = _rows(
        migrated,
        """select ps.provider, ps.provider_symbol, l.exchange, l.symbol
           from provider_symbols ps join listings l using (listing_id)""",
    )
    assert {r[1] for r in rows} == {
        "RELIANCE.NS",
        "INFY.BO",
        "^NSEI",
        "TATAMOTORS.NS",
        "HDFCBANK.NS",
    }
    assert {r[0] for r in rows} == {"yahoo"}
    by_symbol = {(r[2], r[3]): r[1] for r in rows}
    assert by_symbol == {
        ("NSE", "RELIANCE"): "RELIANCE.NS",
        ("BSE", "INFY"): "INFY.BO",
        ("NSE", "NIFTY"): "^NSEI",
        ("NSE", "TATAMOTORS"): "TATAMOTORS.NS",
        ("NSE", "HDFCBANK"): "HDFCBANK.NS",
    }


def test_legacy_parked(migrated):
    assert _scalar(migrated, "select count(*) from legacy.ohlcv_1d") == 4
    assert _scalar(migrated, "select count(*) from public.ohlcv_1d") == 0
    assert _scalar(migrated, "select to_regclass('public.ohlcv_daily')") is None
    for table in LEGACY_TABLES:
        assert _scalar(migrated, "select to_regclass(%s)", (f"legacy.{table}",)) is not None, table
    for seq in LEGACY_SEQUENCES:
        kind = _scalar(
            migrated,
            """select c.relkind from pg_class c join pg_namespace n on n.oid = c.relnamespace
               where n.nspname = 'legacy' and c.relname = %s""",
            (seq,),
        )
        assert kind == "S", seq
    # Parked legacy rows are untouched.
    assert _scalar(migrated, "select close from legacy.ohlcv_1d where symbol = 'NIFTY'") == (
        24398.9171819
    )
    assert _scalar(migrated, "select count(*) from legacy.signal where id = 4217") == 1


def test_new_tables_keyed_by_listing(migrated):
    for table in LISTING_KEYED:
        cols = {
            r[0]: r[1]
            for r in _rows(
                migrated,
                """select column_name, is_nullable from information_schema.columns
                   where table_schema = 'public' and table_name = %s""",
                (table,),
            )
        }
        assert cols.get("listing_id") == "NO", table
        assert "symbol" not in cols and "exchange" not in cols, table
        fk_target = _scalar(
            migrated,
            """select confrelid::regclass::text from pg_constraint
               where conrelid = %s::regclass and contype = 'f'""",
            (f"public.{table}",),
        )
        assert fk_target == "listings", table
    for table in ["ta_daily", "signal", "swing_signals"]:
        assert (
            _scalar(
                migrated,
                """select is_nullable from information_schema.columns
                   where table_schema = 'public' and table_name = %s
                     and column_name = 'calc_version'""",
                (table,),
            )
            == "NO"
        ), table
    assert (
        _scalar(
            migrated,
            """select is_nullable from information_schema.columns
               where table_schema = 'public' and table_name = 'ingest_runs'
                 and column_name = 'provider'""",
        )
        == "NO"
    )
    pk = _scalar(
        migrated,
        """select pg_get_constraintdef(oid) from pg_constraint
           where conrelid = 'public.ohlcv_1d'::regclass and contype = 'p'""",
    )
    assert pk == "PRIMARY KEY (listing_id, ts)"
    price_types = _rows(
        migrated,
        """select column_name, data_type from information_schema.columns
           where table_schema = 'public' and table_name = 'ohlcv_1d'
             and column_name in ('open', 'high', 'low', 'close', 'volume')
           order by column_name""",
    )
    assert price_types == [
        ("close", "double precision"),
        ("high", "double precision"),
        ("low", "double precision"),
        ("open", "double precision"),
        ("volume", "bigint"),
    ]


def test_chunk_intervals(migrated):
    intervals = dict(
        _rows(
            migrated,
            """select hypertable_name, extract(epoch from time_interval) / 86400
               from timescaledb_information.dimensions where hypertable_schema = 'public'""",
        )
    )
    assert intervals["ohlcv_1d"] == 365
    assert intervals["ta_daily"] == 365
    assert intervals["ohlcv_1w"] == 3650
    assert intervals["ohlcv_1mo"] == 3650
    for table in ["ohlcv_1m", "ohlcv_5m", "ohlcv_15m", "ohlcv_75m"]:
        assert intervals[table] == 7, table
    assert "raw_eod_bars" in intervals


def test_retention_policies(migrated):
    rows = _rows(
        migrated,
        """select hypertable_name, config->>'drop_after' from timescaledb_information.jobs
           where proc_name = 'policy_retention' and hypertable_schema = 'public'""",
    )
    assert dict(rows) == {
        "ohlcv_1m": "90 days",
        "ohlcv_5m": "365 days",
        "ohlcv_15m": "730 days",
        "ohlcv_75m": "1825 days",
    }


def test_raw_eod_bars_shape(migrated):
    pk = _scalar(
        migrated,
        """select pg_get_constraintdef(oid) from pg_constraint
           where conrelid = 'public.raw_eod_bars'::regclass and contype = 'p'""",
    )
    assert pk == "PRIMARY KEY (id, fetched_at)"
    dim = _scalar(
        migrated,
        """select column_name from timescaledb_information.dimensions
           where hypertable_schema = 'public' and hypertable_name = 'raw_eod_bars'""",
    )
    assert dim == "fetched_at"
    cols = [
        r[0]
        for r in _rows(
            migrated,
            """select column_name from information_schema.columns
               where table_schema = 'public' and table_name = 'raw_eod_bars'
               order by ordinal_position""",
        )
    ]
    assert cols == [
        "id",
        "ingest_run_id",
        "provider",
        "provider_symbol",
        "timeframe",
        "bar_ts",
        "payload",
        "fetched_at",
    ]


def test_ohlcv_latest_view(migrated):
    cols = [
        r[0]
        for r in _rows(
            migrated,
            """select column_name from information_schema.columns
               where table_schema = 'public' and table_name = 'ohlcv_latest'
               order by ordinal_position""",
        )
    ]
    assert cols == ["listing_id", "ts", "open", "high", "low", "close", "volume"]
    with psycopg.connect(migrated) as conn:
        lid = conn.execute("select listing_id from listings where symbol = 'RELIANCE'").fetchone()[
            0
        ]
        conn.execute(
            """insert into ohlcv_1d (ts, listing_id, open, high, low, close, volume) values
               ('2026-11-09', %(l)s, 1, 2, 0.5, 1.5, 10),
               ('2026-11-10', %(l)s, 1, 2, 0.5, 1.75, 11)""",
            {"l": lid},
        )
        latest = conn.execute("select listing_id, close from ohlcv_latest").fetchall()
        conn.rollback()
    assert latest == [(lid, 1.75)]


def test_empty_database_applies(fresh_db, migrate):
    migrate(fresh_db, until="20261111000007")
    assert _scalar(fresh_db, "select count(*) from listings") == 0
    assert _scalar(fresh_db, "select count(*) from legacy.ohlcv_1d") == 0


def test_down_restores_legacy(migrated):
    with psycopg.connect(migrated) as conn:
        conn.execute(_down_sql(MIGRATION_07))
    assert _scalar(migrated, "select count(*) from public.ohlcv_1d") == 4
    assert _scalar(migrated, "select to_regnamespace('legacy')") is None
    for table in LEGACY_TABLES:
        assert _scalar(migrated, "select to_regclass(%s)", (f"public.{table}",)) is not None, table
    assert {
        r[0]
        for r in _rows(
            migrated,
            """select column_name from information_schema.columns
               where table_schema = 'public' and table_name = 'ohlcv_1d'""",
        )
    } >= {"symbol", "exchange"}
    assert _scalar(migrated, "select to_regclass('public.raw_eod_bars')") is None
    assert _scalar(migrated, "select count(*) from listings") == 0
    assert _scalar(migrated, "select count(*) from provider_symbols") == 0
    # Old view is back, over legacy ohlcv_daily.
    view_cols = [
        r[0]
        for r in _rows(
            migrated,
            """select column_name from information_schema.columns
               where table_schema = 'public' and table_name = 'ohlcv_latest'
               order by ordinal_position""",
        )
    ]
    assert view_cols == ["ts", "symbol", "exchange", "open", "high", "low", "close", "volume"]
    # Sequences are back in public and still own their columns.
    for seq in LEGACY_SEQUENCES:
        assert _scalar(migrated, "select to_regclass(%s)", (f"public.{seq}",)) is not None, seq
    with psycopg.connect(migrated) as conn:
        new_id = conn.execute(
            """insert into ingest_runs (symbol, exchange, timeframe) values ('TCS', 'BSE', '1d')
               returning id"""
        ).fetchone()[0]
        conn.rollback()
    assert new_id >= 1
    # Retention jobs are still attached to the restored intraday tables.
    retention = _rows(
        migrated,
        """select hypertable_schema, hypertable_name from timescaledb_information.jobs
           where proc_name = 'policy_retention'""",
    )
    assert {r[1] for r in retention} == {"ohlcv_1m", "ohlcv_5m", "ohlcv_15m", "ohlcv_75m"}
    assert {r[0] for r in retention} == {"public"}

    # 06 down then removes the identity tables.
    with psycopg.connect(migrated) as conn:
        conn.execute(_down_sql(MIGRATION_06))
    for table in ["companies", "listings", "provider_symbols"]:
        assert _scalar(migrated, "select to_regclass(%s)", (f"public.{table}",)) is None, table


def test_reapply_after_down(migrated, migrate):
    """07 down followed by 07 up again gives the same parked state (rollback is repeatable)."""
    with psycopg.connect(migrated) as conn:
        conn.execute(_down_sql(MIGRATION_07))
    body = MIGRATION_07.read_text().split("-- migrate:down", 1)[0]
    with psycopg.connect(migrated) as conn:
        conn.execute(body)
    assert _scalar(migrated, "select count(*) from legacy.ohlcv_1d") == 4
    assert _scalar(migrated, "select count(*) from listings where is_active") == 5
