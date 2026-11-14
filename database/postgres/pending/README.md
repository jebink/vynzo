# pending

Migrations that are written but **not yet approved**. dbmate never sees this directory
(`scripts/migrate.sh` passes `--migrations-dir /db/migrations`), so `make migrate` does not apply them.

**Move files into `../migrations` only after the user approves, and move all four together.**

The legacy drop is split into four migrations, applied in order, each in its own transaction.
Dropping a hypertable locks every chunk and its indexes and constraints (measured 9-11 locks per
chunk), and `legacy.ohlcv_1d`, `legacy.ta_daily` and `legacy.ohlcv_1w` each have 1,872 chunks on
dev. One `DROP SCHEMA legacy CASCADE` would need about 63k locks, twice what the dev lock table
holds (`max_locks_per_transaction` 256 × 122 slots = 31,232).

Peak `pg_locks` rows per file, measured on a restore of the 2026-11-11 dev dump with the same lock
settings (`vynzo_drop_rehearsal`, since dropped):

| File | Peak locks | Time |
|---|---|---|
| `…12_drop_legacy_ohlcv_1d` | 20,621 | 1.9 s |
| `…13_drop_legacy_ta_daily` | 16,871 | 1.5 s |
| `…14_drop_legacy_ohlcv_1w` | 20,622 | 1.8 s |
| `…15_drop_legacy_schema` | 5,342 | 0.4 s |

The largest uses two-thirds of the lock table, which is shared by all sessions. **Run the drop when
nothing else holds many locks:** not during the nightly `pg_dump` (02:30 IST, which locks every
chunk it dumps) or the 17:00 IST job chain, and only after the pre-drop dump has finished.

| File | Drops |
|---|---|
| `20261111000012_drop_legacy_ohlcv_1d.sql` | `legacy.ohlcv_1d` |
| `20261111000013_drop_legacy_ta_daily.sql` | `legacy.ta_daily` |
| `20261111000014_drop_legacy_ohlcv_1w.sql` | `legacy.ohlcv_1w` |
| `20261111000015_drop_legacy_schema.sql` | every other legacy table (`ohlcv_1mo`, the intraday tables, `ohlcv_daily`, `ingest_runs`, `ohlcv_gaps`, `signal`, `swing_signals`), then `DROP SCHEMA legacy CASCADE` (sequences, retention jobs) |

All four are **irreversible**. Each down section refuses ("restore from backup: legacy data is
gone"). If one fails, the ones before it stay applied, so the fix is to re-run `scripts/migrate.sh up`
after the cause is cleared, not a rollback.

**Approval needed:** the user has seen the copy verification (legacy vs new row counts per table,
parity check) and said yes, and a verified `pg_dump` backup exists.

Integration tests apply this directory only when asked (`apply_migrations(url, include_pending=True)`).
