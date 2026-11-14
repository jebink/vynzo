"""Copy migrations 08-11 (legacy.* -> listing-keyed public.*) and the legacy drop (12-15)."""

from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "database" / "postgres" / "migrations"
PENDING_DIR = ROOT / "database" / "postgres" / "pending"
LAST_COPY = "20261111000011"
COPY_VERSIONS = ["20261111000008", "20261111000009", "20261111000010", "20261111000011"]

# Every legacy table that is copied, with the number of rows the seed puts in it.
SEEDED_COUNTS = {
    "ohlcv_1m": 0,
    "ohlcv_5m": 3,
    "ohlcv_15m": 1,
    "ohlcv_75m": 1,
    "ohlcv_1d": 4,
    "ohlcv_1w": 1,
    "ohlcv_1mo": 1,
    "ta_daily": 2,
    "ingest_runs": 2,
    "ohlcv_gaps": 1,
    "signal": 2,
    "swing_signals": 1,
}
COPIED_TABLES = list(SEEDED_COUNTS)
ID_TABLES = ["signal", "swing_signals", "ingest_runs", "ohlcv_gaps"]
VERSIONED_TABLES = ["ta_daily", "signal", "swing_signals"]


def _rows(url: str, query, params=None) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(query, params).fetchall()


def _scalar(url: str, query, params=None):
    return _rows(url, query, params)[0][0]


def _down_sql(version: str) -> str:
    (path,) = MIGRATIONS_DIR.glob(f"{version}_*.sql")
    return path.read_text().split("-- migrate:down", 1)[1]


def _legacy_columns(url: str, table: str) -> list[str]:
    """Legacy columns of `table` other than symbol/exchange, in table order."""
    return [
        r[0]
        for r in _rows(
            url,
            """select column_name from information_schema.columns
               where table_schema = 'legacy' and table_name = %s
                 and column_name not in ('symbol', 'exchange')
               order by ordinal_position""",
            (table,),
        )
    ]


@pytest.fixture
def copied(fresh_db, migrate, seed_legacy):
    """Seeded legacy data copied by 08-11, with schema `legacy` still in place (before the drop)."""
    seed_legacy(fresh_db)
    migrate(fresh_db, until=LAST_COPY)
    return fresh_db


def _assert_identical(url: str) -> None:
    for table in COPIED_TABLES:
        cols = _legacy_columns(url, table)
        assert cols, table
        legacy_cols = sql.SQL(", ").join(sql.Identifier("l", c) for c in cols)
        new_cols = sql.SQL(", ").join(sql.Identifier("n", c) for c in cols)
        legacy_rows = _rows(
            url,
            sql.SQL(
                "select l.exchange::text, l.symbol, {} from legacy.{} l order by 1, 2, 3"
            ).format(legacy_cols, sql.Identifier(table)),
        )
        new_rows = _rows(
            url,
            sql.SQL(
                """select li.exchange::text, li.symbol, {} from public.{} n
                   join listings li using (listing_id) order by 1, 2, 3"""
            ).format(new_cols, sql.Identifier(table)),
        )
        assert len(legacy_rows) == SEEDED_COUNTS[table], table
        # Python float == is exact; None == None covers the NULL columns.
        assert new_rows == legacy_rows, table

        # Same check in SQL: no legacy row lacks a twin equal on every column.
        same = sql.SQL(" and ").join(
            sql.SQL("n.{c} is not distinct from l.{c}").format(c=sql.Identifier(c)) for c in cols
        )
        missing = _scalar(
            url,
            sql.SQL(
                """select count(*) from legacy.{t} l where not exists (
                     select 1 from public.{t} n join listings li using (listing_id)
                     where li.exchange = l.exchange and li.symbol = l.symbol and {same})"""
            ).format(t=sql.Identifier(table), same=same),
        )
        assert missing == 0, table


def test_values_identical(copied):
    _assert_identical(copied)
    # Spot-check the awkward values survive bit for bit.
    assert (
        _scalar(
            copied,
            """select t.macd_hist from public.ta_daily t join listings li using (listing_id)
               where li.symbol = 'RELIANCE' and t.ts = '2026-11-05 00:00:00+05:30'""",
        )
        == 0.30000000000000004
    )
    assert _rows(
        copied,
        """select ema_200, ema200_slope_20, ret_126 from public.ta_daily
           where ts = '2026-11-06 00:00:00+05:30'""",
    ) == [(None, None, None)]


def test_every_legacy_pair_gets_listing_and_rows(copied):
    for table in COPIED_TABLES:
        legacy = dict(
            (tuple(r[:2]), r[2])
            for r in _rows(
                copied,
                sql.SQL(
                    "select exchange::text, symbol, count(*) from legacy.{} group by 1, 2"
                ).format(sql.Identifier(table)),
            )
        )
        new = dict(
            (tuple(r[:2]), r[2])
            for r in _rows(
                copied,
                sql.SQL(
                    """select li.exchange::text, li.symbol, count(*) from public.{} n
                       join listings li using (listing_id) group by 1, 2"""
                ).format(sql.Identifier(table)),
            )
        )
        assert new == legacy, table
    # The pairs that exist in exactly one legacy table.
    assert _rows(
        copied,
        """select li.symbol, count(*) from public.ohlcv_5m n join listings li using (listing_id)
           where li.symbol = 'TATAMOTORS' group by 1""",
    ) == [("TATAMOTORS", 1)]
    assert _rows(
        copied,
        """select li.symbol, n.signal_type from public.signal n join listings li using (listing_id)
           where li.symbol = 'HDFCBANK'""",
    ) == [("HDFCBANK", "SENTIMENT")]
    assert _scalar(copied, "select count(*) from listings") == 5


def test_ids_and_sequences(copied):
    for table in ID_TABLES:
        legacy_ids = {
            r[0]
            for r in _rows(
                copied, sql.SQL("select id from legacy.{}").format(sql.Identifier(table))
            )
        }
        new_ids = {
            r[0]
            for r in _rows(
                copied, sql.SQL("select id from public.{}").format(sql.Identifier(table))
            )
        }
        assert legacy_ids, table
        assert new_ids == legacy_ids, table
        next_id = _scalar(
            copied, "select nextval(pg_get_serial_sequence(%s, 'id'))", (f"public.{table}",)
        )
        assert next_id == max(new_ids) + 1, table
    assert _scalar(copied, "select count(*) from public.signal where id = 4217") == 1


def test_provenance_labels(copied):
    for table in VERSIONED_TABLES:
        labels = _rows(
            copied,
            sql.SQL("select distinct calc_version from public.{}").format(sql.Identifier(table)),
        )
        assert labels == [("legacy-vinzo-core",)], table
    assert _rows(copied, "select distinct provider from public.ingest_runs") == [("yahoo",)]
    # computed_at takes its default (the copy time).
    assert _scalar(copied, "select count(*) from public.ta_daily where computed_at is null") == 0


def test_guard_raises(fresh_db, migrate, seed_legacy):
    seed_legacy(fresh_db)
    migrate(fresh_db, until="20261111000007")
    with psycopg.connect(fresh_db) as conn:
        conn.execute(
            """insert into legacy.ohlcv_1d (ts, symbol, exchange, open, high, low, close, volume)
               values ('2026-11-06', 'ORPHAN', 'NSE', 1.5, 2.5, 1.25, 2.0, 100)"""
        )
    with pytest.raises(psycopg.errors.RaiseException, match="copy mismatch"):
        migrate(fresh_db, after="20261111000007", until="20261111000008")
    # 08 rolled back as a whole: nothing was copied.
    assert _scalar(fresh_db, "select count(*) from public.ohlcv_1d") == 0


def test_ohlcv_daily_guard(fresh_db, migrate, seed_legacy):
    seed_legacy(fresh_db)
    migrate(fresh_db, until="20261111000007")
    with psycopg.connect(fresh_db) as conn:
        conn.execute(
            """insert into legacy.ohlcv_daily (ts, symbol, exchange, open, high, low, close, volume)
               values ('2026-11-06', 'RELIANCE', 'NSE', 1.5, 2.5, 1.25, 2.0, 100)"""
        )
    migrate(fresh_db, after="20261111000007", until="20261111000010")
    with pytest.raises(psycopg.errors.RaiseException, match="legacy.ohlcv_daily not empty: 1 rows"):
        migrate(fresh_db, after="20261111000010", until="20261111000011")
    assert _scalar(fresh_db, "select count(*) from public.signal") == 0


def test_empty_db_noop(fresh_db, migrate):
    applied = migrate(fresh_db)
    assert [v for v in applied if v in COPY_VERSIONS] == COPY_VERSIONS
    for table in COPIED_TABLES:
        assert (
            _scalar(
                fresh_db, sql.SQL("select count(*) from public.{}").format(sql.Identifier(table))
            )
            == 0
        ), table
    for table in ID_TABLES:
        assert (
            _scalar(
                fresh_db, "select nextval(pg_get_serial_sequence(%s, 'id'))", (f"public.{table}",)
            )
            == 1
        ), table


def test_down_truncates_and_up_recopies(copied, migrate):
    for version in reversed(COPY_VERSIONS):
        with psycopg.connect(copied) as conn:
            conn.execute(_down_sql(version))
    for table in COPIED_TABLES:
        assert (
            _scalar(copied, sql.SQL("select count(*) from public.{}").format(sql.Identifier(table)))
            == 0
        ), table
        assert (
            _scalar(copied, sql.SQL("select count(*) from legacy.{}").format(sql.Identifier(table)))
            == (SEEDED_COUNTS[table])
        ), table
    for table in ID_TABLES:
        assert (
            _scalar(
                copied, "select nextval(pg_get_serial_sequence(%s, 'id'))", (f"public.{table}",)
            )
            == 1
        ), table
    # Listings stay (07 owns them), so the copies can run again.
    assert _scalar(copied, "select count(*) from listings") == 5
    assert migrate(copied, after="20261111000007", until=LAST_COPY) == COPY_VERSIONS
    _assert_identical(copied)


# The legacy drop, in order: (version, legacy tables it drops). The last one also drops schema
# `legacy`. Split so no single transaction exceeds the dev lock table. Approved and moved out of
# pending/ on 2026-11-14.
LEGACY_DROPS = [
    ("20261111000012", ["ohlcv_1d"]),
    ("20261111000013", ["ta_daily"]),
    ("20261111000014", ["ohlcv_1w"]),
    (
        "20261111000015",
        [
            "ohlcv_1mo",
            "ohlcv_1m",
            "ohlcv_5m",
            "ohlcv_15m",
            "ohlcv_75m",
            "ohlcv_daily",
            "ingest_runs",
            "ohlcv_gaps",
            "signal",
            "swing_signals",
        ],
    ),
]


def _legacy_tables(url: str) -> set[str]:
    return {r[0] for r in _rows(url, "select tablename from pg_tables where schemaname = 'legacy'")}


def test_drop_files_are_the_split_drop():
    assert not list(PENDING_DIR.glob("*drop_legacy*"))
    names = sorted(p.name for p in MIGRATIONS_DIR.glob("*drop_legacy*.sql"))
    assert [n.split("_", 1)[0] for n in names] == [v for v, _ in LEGACY_DROPS]


def test_drops_remove_legacy_in_order(copied, migrate):
    assert _scalar(copied, "select to_regnamespace('legacy')") is not None
    remaining = _legacy_tables(copied)
    assert remaining == set(SEEDED_COUNTS) | {"ohlcv_daily"}
    prev = LAST_COPY
    for version, tables in LEGACY_DROPS:
        assert migrate(copied, after=prev, until=version) == [version]
        remaining -= set(tables)
        assert _legacy_tables(copied) == remaining, version
        prev = version
    assert remaining == set()
    assert _scalar(copied, "select to_regnamespace('legacy')") is None
    assert (
        _scalar(
            copied,
            """select count(*) from timescaledb_information.hypertables
               where hypertable_schema = 'legacy'""",
        )
        == 0
    )
    assert (
        _scalar(
            copied,
            """select count(*) from timescaledb_information.jobs
               where hypertable_schema = 'legacy'""",
        )
        == 0
    )
    # The copied data is untouched by the drop.
    for table, n in SEEDED_COUNTS.items():
        assert (
            _scalar(copied, sql.SQL("select count(*) from public.{}").format(sql.Identifier(table)))
            == n
        ), table


@pytest.mark.parametrize("version", [v for v, _ in LEGACY_DROPS])
def test_drop_down_refuses(fresh_db, version):
    (path,) = MIGRATIONS_DIR.glob(f"{version}_*.sql")
    down = path.read_text().split("-- migrate:down", 1)[1]
    with pytest.raises(psycopg.errors.RaiseException, match="restore from backup"):
        with psycopg.connect(fresh_db) as conn:
            conn.execute(down)
