# postgres

PostgreSQL 16 + TimescaleDB 2.31, migrations managed by [dbmate](https://github.com/amacneil/dbmate)
(run through Docker, so nothing needs installing).

```bash
make migrate                         # apply pending migrations (uses DATABASE_URL from .env)
scripts/migrate.sh status            # list applied / pending
scripts/migrate.sh new add_companies # create database/postgres/migrations/<timestamp>_add_companies.sql
```

## Rules

- One file per change, named `<UTC timestamp>_<what>.sql`, with `-- migrate:up` and `-- migrate:down` sections.
- Never edit a migration that has been applied anywhere. Write a new one.
- dbmate wraps each migration in a transaction. Don't add `BEGIN`/`COMMIT`. For statements that
  can't run in a transaction (e.g. `CREATE INDEX CONCURRENTLY`), add `-- migrate:up transaction:false`.

## Baseline

`20261108000001` … `20261108000005` are the schema carried over from vinzo-core
(`ohlcv_*` hypertables, `ta_daily`, `signal`, `swing_signals`, `ingest_runs`, `ohlcv_gaps`).
They are idempotent (`IF NOT EXISTS`), so running them against the existing database only records
them in dbmate's `schema_migrations` table.

## Instrument identity and the legacy move

| Migration | What it does | Down |
|---|---|---|
| `20261111000006_instrument_identity` | `companies`, `listings` (one per exchange + symbol), `provider_symbols` (architecture rule 1). | Drops the three tables. |
| `20261111000007_park_legacy_and_create_tables` | Moves every vinzo-core table and its sequence into schema `legacy`, creates an active listing plus a Yahoo provider symbol for every legacy (symbol, exchange), and creates the new tables keyed by `listing_id` (empty), plus `raw_eod_bars` and the rebuilt `ohlcv_latest` view. | Drops the new tables, deletes those listings and moves `legacy.*` back to `public`. |
| `20261111000008_copy_ohlcv_1d` | Copies `legacy.ohlcv_1d`. | `TRUNCATE` |
| `20261111000009_copy_ta_daily` | Copies `legacy.ta_daily`, `calc_version = 'legacy-vinzo-core'`. | `TRUNCATE` |
| `20261111000010_copy_ohlcv_1w_1mo` | Copies `legacy.ohlcv_1w` and `legacy.ohlcv_1mo`. | `TRUNCATE` |
| `20261111000011_copy_small_tables` | Copies intraday bars, `ingest_runs` (`provider = 'yahoo'`), `ohlcv_gaps`, `signal` and `swing_signals` (`calc_version = 'legacy-vinzo-core'`). Keeps the original ids and `setval`s each id sequence past the max. Refuses to run if `legacy.ohlcv_daily` has rows (it is neither copied nor a listing source). | `TRUNCATE … RESTART IDENTITY` |

The copies are plain `INSERT … SELECT` joined to `listings` on (exchange, symbol): same column
types, no casts, no rounding. Each copy migration ends with a guard that raises `copy mismatch`
unless the row count of every `legacy.X` equals that of `public.X`, and for bar tables also
`sum(close)` and `sum(volume)`. The close sum is taken over `close::text::numeric`, which is exact
and independent of row order, so a one-ulp change is caught and a different scan order is not
a false alarm. A legacy row with no listing would be dropped by the join, so it trips the count.

The copy is split into four migrations to keep each transaction's lock count well under the
dev server's lock table (~1,900 legacy chunks per large table). A failed copy rolls back only
itself, and `legacy.*` stays intact, so it can be re-run.

`legacy.*` is kept until the user approves the drop: see [`pending/`](pending/README.md). The drop
is four migrations (`…12`–`…15`: `ohlcv_1d`, `ta_daily`, `ohlcv_1w`, then the rest plus
`DROP SCHEMA legacy CASCADE`), split for the same lock-table reason; after approval all four move
into `migrations/` together.
Rollback before the drop: `scripts/migrate.sh rollback` repeatedly (11 → 06). After the drop:
restore from backup.

**After cutover (once the pipeline has written new data), roll back through 07, never 11 alone.**
`…11` empties the small tables with `RESTART IDENTITY`, so new `ingest_run` ids could be reused
while `raw_eod_bars` rows still reference the old ones. Anything written after cutover is lost.
See [`docs/runbooks/identity-migration.md`](../../docs/runbooks/identity-migration.md).
