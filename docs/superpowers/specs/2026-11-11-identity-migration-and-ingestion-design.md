# Instrument-identity migration, EOD ingestion and daily analytics

Date: 2026-11-11 · Status: draft, awaiting approval

## Intent

VYNZO replaced vinzo-core with a new architecture (see `docs/architecture.md`). The data vinzo-core
collected still lives in the old shape on the dev server database (`192.168.31.11`, db `market`):
about 2.3M rows keyed by `(symbol, exchange)` text. We want that data in the new schema
**without re-fetching it from any provider**, the old tables gone, and the daily pipeline
(EOD prices → indicators → high-volume-buy signals → freshness) running again on new code that
writes to the new schema.

Architecture rules that drive the shape (from `docs/architecture.md`):

- **Rule 1:** one instrument identity system. Company IDs, exchange listing IDs and provider tokens
  stay distinct.
- **Rule 2:** raw data is immutable; normalized data can be rebuilt from retained raw data.
- **Rule 3:** schema changes only in `database/postgres/migrations` (dbmate). Services never create or
  alter tables.
- **Rule 5:** every analytics result carries provenance and a version.
- **Rule 6:** ingestion supports replay and validation.

## Goals

1. Add the identity model: `companies`, `listings` and `provider_symbols`.
2. Move every legacy row into new tables keyed by `listing_id`, with no value changed and no row lost.
3. Fill in the `market-ingestion` stubs: `eod`, `backfill`, `freshness`, plus a new `sync-reference`
   job.
4. Port two `analytics-worker` jobs, `indicators` and `high-volume-buy`, with the same formulas as
   vinzo-core.
5. Drop the old tables, but only after verification and after the user explicitly approves.

## Non-goals

- Porting the `sentiment` or `swing` jobs. Their legacy rows are migrated, but no new ones are
  produced.
- Ingesting intraday bars (1m/5m/15m/75m). vinzo-core never did this daily. Legacy intraday rows are
  migrated, and the tables stay empty-ready.
- API endpoints or web pages for market data.
- A licensed data vendor. Yahoo stays the only provider, behind the provider interface.
- Expanding the universe beyond the 278 listings that have data today.

## Anti-goals (failure even if it "works")

- The migration alters, rounds or drops any legacy bar, indicator or signal value. After cutover the
  live pipeline owns the data and may refresh the recent window (see §4 and §5), just as vinzo-core
  did.
- Re-downloading history to rebuild data we already hold.
- The reference sync silently activating thousands of new symbols for daily ingestion.
- Old tables dropped before row counts are verified and the user has said yes.

## Current state (verified 2026-11-11)

**Dev server DB** (PostgreSQL 16.15, TimescaleDB 2.31.0, 1.18 GB, no `schema_migrations` table).
Its columns, indexes and constraints are identical to baseline migrations `20261108000001`–`…05`.

| Table | Rows | Notes |
|---|---|---|
| `ohlcv_1d` | 1,021,273 | hypertable; 1991-01-02 → 2026-11-09 |
| `ta_daily` | 999,504 | hypertable |
| `ohlcv_1w` | 214,042 | hypertable |
| `ohlcv_1mo` | 48,790 | hypertable |
| `ohlcv_5m` / `15m` / `75m` | 4,384 / 1,492 / 345 | hypertables, retention policies 365/730/1825 d |
| `ohlcv_1m`, `ohlcv_daily` | 0 | `ohlcv_daily` is an unused leftover |
| `ingest_runs` | 1,712 | |
| `ohlcv_gaps` | 1,945 | |
| `signal` | 386 | 260 `HIGH_VOLUME_BUY`, 126 `SENTIMENT` |
| `swing_signals` | 151 | |
| `ohlcv_latest` | view | latest `ohlcv_1d` bar per symbol |

**Distinct `(symbol, exchange)` across all tables: 278.** That is 276 NSE (275 equities plus the
`NIFTY` index) and 2 BSE (`INFY`, `TCS`). All 275 NSE equities appear in
`data/reference/nse_equities.csv` with name and ISIN. `INFY` and `TCS` on BSE are the same companies
as their NSE listings. `NIFTY` maps to Yahoo `^NSEI`.

**Old cron on the dev server** last ran 2026-11-11 04:57 UTC. The user accepts that dev data stops
updating from cutover until the new pipeline runs.

**Reference code:** vinzo-core is archived at `~/Desktop/vinzo-core-backup-2026-11-11.tar.gz`. Port
from `market_data/{provider,ingest,daily,indicators}.py` and `market_data/detectors/high_volume_buy.py`.
The archive contains a `.env` with live credentials, so never copy it into the repo.

## Design

### 1. Identity model (new migration)

```
companies         company_id  bigint identity PK
                  name        text not null
                  isin        text unique          -- equity share ISIN (INE…)
                  created_at  timestamptz default now()

listings          listing_id  bigint identity PK
                  company_id  bigint null → companies   -- null for indices
                  exchange    exchange_code not null     -- existing domain: NSE | BSE
                  symbol      text not null
                  kind        text not null check (kind in ('equity','index'))
                  series      text                       -- EQ, BE … (from reference file)
                  listed_on   date
                  is_active   boolean not null default false   -- in the daily-ingest universe
                  unique (exchange, symbol)

provider_symbols  provider        text not null        -- 'yahoo'
                  provider_symbol text not null        -- 'RELIANCE.NS', 'INFY.BO', '^NSEI'
                  listing_id      bigint not null → listings
                  primary key (provider, provider_symbol)
                  unique (provider, listing_id)
```

"Active" means the listing is ingested daily. Only the 278 migrated listings start out active.

### 2. Market-data tables keyed by `listing_id`

Each table keeps its current name and columns, with `listing_id bigint not null references listings`
replacing `symbol` + `exchange`.

- `ohlcv_1m/5m/15m/75m/1d/1w/1mo`: PK `(listing_id, ts)`, hypertable on `ts`, index
  `(listing_id, ts desc)`. The same retention policies are re-added to the intraday tables. Column
  types stay the same (`double precision` prices, `bigint` volume) so values copy bit for bit.
- **Chunk intervals:** 365 days for `ohlcv_1d` and `ta_daily`, 3650 days for `ohlcv_1w` and
  `ohlcv_1mo`, and 7 days for intraday tables (unchanged, since retention drops by chunk). The
  legacy tables use 7-day chunks for everything, about 1,900 chunks each. That is over-chunked for
  daily data, and copying it all at once would exceed the lock table (see §3).
- `ta_daily`: all current indicator columns, plus `calc_version text not null` and
  `computed_at timestamptz not null default now()`. PK `(listing_id, ts)`.
- `signal`: same columns plus `calc_version text not null`. Unique
  `(listing_id, signal_type, as_of)`.
- `swing_signals`: same columns plus `calc_version text not null`. Unique `(listing_id, as_of)`.
- `ingest_runs`: `listing_id` plus a new `provider text not null`.
- `ohlcv_gaps`: `listing_id`.
- `ohlcv_latest` view: rebuilt over the new `ohlcv_1d`.
- `ohlcv_daily` is not recreated.
- **New** `raw_eod_bars` (rule 2): append-only and never updated. Columns: `id`, `ingest_run_id`,
  `provider`, `provider_symbol`, `timeframe`, `bar_ts`, `payload jsonb` (exactly what the provider
  returned for that bar) and `fetched_at`. Hypertable on `fetched_at`. Legacy bars have no raw
  records, which is accepted and documented.

Provenance values for migrated rows: `calc_version = 'legacy-vinzo-core'` and
`ingest_runs.provider = 'yahoo'`. Every legacy row carries this label because the old code did not
record versions.

### 3. Moving the data (migrations, in order)

1. **Baseline the dev DB.** Running `make migrate` against dev records `…01`–`…05` in
   `schema_migrations`. They are idempotent, so nothing changes.
2. **`…06_instrument_identity`:** creates `companies`, `listings` and `provider_symbols`.
3. **`…07_park_legacy_and_create_tables`:**
   - `CREATE SCHEMA legacy` and `ALTER TABLE … SET SCHEMA legacy` for every old table and the
     sequences that go with them. Drop the old view.
   - Insert a listing for every distinct legacy `(symbol, exchange)`, marked `is_active = true`.
     `NIFTY` gets `kind = 'index'`; everything else gets `'equity'`. `company_id` stays null for
     now and is filled by `sync-reference`.
   - Insert `provider_symbols`: `SYMBOL.NS` for NSE, `SYMBOL.BO` for BSE, and `^NSEI` for `NIFTY`
     (matching vinzo-core's `to_ticker`).
   - Create all the new tables, empty.
4. **Copy migrations, one per large table:** `…08_copy_ohlcv_1d`, `…09_copy_ta_daily`,
   `…10_copy_ohlcv_1w_1mo`, `…11_copy_small_tables` (intraday, signals, runs, gaps). Each one does
   `INSERT … SELECT` from `legacy.*` joined to `listings`. Keep the original `id` values in
   `signal`, `swing_signals`, `ingest_runs` and `ohlcv_gaps`, and `setval` their sequences past the
   max.
   - **Guard in each:** a `DO` block compares the row count of each `legacy.X` with its new table,
     and also checks `sum(close)` and `sum(volume)` per table for bars. It raises on any difference.
   - **Why split:** dev has `max_locks_per_transaction=256` × `max_connections=100`, a shared lock
     table of 25,600. Reading ~1,900 legacy chunks × 3 relations each (chunk plus 2 indexes) per big
     table means four tables in one transaction would need ~22k locks, which is too close to the
     limit. Splitting gives up the single all-or-nothing rollback, which is fine because `legacy.*`
     stays intact until the drop: a failed copy rolls back only itself and can be re-run.
   - If a single table still exceeds the limit in rehearsal, batch that copy by `ts` range inside a
     `transaction:false` migration. Raising `max_locks_per_transaction` (which needs a DB restart)
     is the last resort.

   Because migration 07 creates listings from the legacy data itself, nothing depends on the CSV.
   On a fresh database the legacy tables are empty and the copies are no-ops.
5. **`market-ingestion sync-reference`:** an idempotent job.
   - It loads `data/reference/nse_equities.csv` into `companies` (matched on ISIN) and NSE
     `listings` (matched on exchange and symbol), filling `company_id`, `series` and `listed_on`.
     That adds about 2,370 inactive NSE listings.
   - It does **not** create BSE listings from `bse_all_equities.csv`, because that file has no ISIN
     or name and linking by symbol alone is unreliable. It only links **existing** BSE listings (INFY
     and TCS) to the company of the NSE listing with the same symbol, and logs any BSE listing it
     can't link.
   - New listings are inserted with `is_active = false` and no `provider_symbols` row. Activating a
     listing (a future admin step, out of scope) adds the provider symbol. The job never changes
     `is_active` on existing listings.
6. **`…12`–`…15` drop legacy:** written now but kept in `database/postgres/pending/`, because
   dbmate applies everything in `migrations/` on the next `make migrate`. They move into
   `migrations/` only after the user approves.
   - The drop is split into four files: legacy `ohlcv_1d`, legacy `ta_daily`, legacy `ohlcv_1w`,
     then the rest plus `DROP SCHEMA legacy`.
   - Why: a single `DROP SCHEMA … CASCADE` would hold ~40k locks, more than dev's ~31k lock table.
   - Rehearsed peaks: 20.6k, 16.9k, 20.6k and 5.3k locks.

### 4. `market-ingestion` service

The layout follows the existing stubs:

- `providers/vendor/yahoo.py`: implements `Provider` from `providers/base.py` using `yfinance`. It is
  ported from vinzo-core `provider.fetch_ohlcv`, with `auto_adjust=False` and the same
  period/start/end handling, and returns `RawRecord`s, one per bar. vinzo-core's fallback retries
  the **same** ticker with `yf.Ticker(t).history()` when `yf.download` returns nothing. It never
  switches `.NS` to `.BO`, so each listing only ever receives bars from its own provider symbol.
- `instruments/`: resolves provider symbol ↔ `listing_id`, lists active listings, and runs
  `sync-reference`.
- `normalization/`: converts a `RawRecord` into a bar `{listing_id, ts (UTC), open, high, low, close,
  volume}`.
- `validation/`: ported `validate_ohlcv` (drop NaN, OHLC consistency, volume ≥ 0, dedupe by ts keeping
  the last), plus a rule that rejects bars dated after the last complete session.
- `checkpoint/`: the last stored `ts` per (listing, timeframe). No separate table; `max(ts)` is the
  checkpoint.
- `recovery/`: gap detection (ported `detect_gaps`) and the backfill logic.
- `publisher/`: database writes: raw insert, bar upsert, `ingest_runs` and `ohlcv_gaps`.

Jobs (`python -m market_ingestion <job>`):

| Job | Does |
|---|---|
| `eod` | For each active listing, for timeframes `1d`, `1w` and `1mo`, run one `ingest_runs` row through these steps: fetch from `checkpoint − overlap` (7 d / 21 d / 45 d, with 1mo snapped to the 1st) to the last complete session (16:00 IST cutoff); insert raw rows; normalize; validate; upsert bars; detect and record gaps; finish the run. A listing with no bars gets full history (`period=max`). Errors stay isolated per listing. Runs on 4 worker threads. |
| `backfill` | `[--listing EXCH:SYMBOL]`: re-fetches the window of each unresolved `ohlcv_gaps` row and marks it resolved if bars now exist. Also runs full history for active listings that have no bars. |
| `freshness` | Ported `check_freshness`: newest `ohlcv_1d` bar against the expected session (18:00 IST cutoff, one weekday of slack). Pushes to `KUMA_PUSH_URL` if set. Exits 1 when stale. |
| `sync-reference` | See §3.4. |

**Overwrites:** bar upserts use `ON CONFLICT DO UPDATE`. The overlap window exists so that
still-forming weekly and monthly bars and Yahoo's late corrections get refreshed, which is what
vinzo-core did. So the first `eod` run may update migrated bars inside that window (at most 45 days),
and that is expected. The raw table keeps what Yahoo sent each time.

**Exit code for `eod`:** 0 unless more than 10% of listings fail or there is a database or
configuration error. The cron chain uses `&&`, so a few flaky symbols must not block indicators.

### 5. `analytics-worker` jobs

- `indicators`: for every active listing with 1d bars (as vinzo-core did after each ingest, so bar
  revisions inside the eod overlap window are picked up), load all of its 1d bars, run the ported `compute_ta_frame` with identical formulas,
  and upsert the last 15 rows with `calc_version = 'ta-1'`.
- `high-volume-buy [--days N] [--as-of DATE]`: ported detector (lookback 20, multiplier 2.0, green day
  and up day and volume ≥ 2× average). Upserts into `signal` with `calc_version = 'hvb-1'`. Same
  `rationale` text and `meta` keys as vinzo-core.

Recomputed `ta_daily` rows replace overlapping `legacy-vinzo-core` rows and take the `ta-1` label,
because they are a fresh calculation. `high-volume-buy` upserts on `(listing_id, signal_type, as_of)`
in the same way.

**Parity check:** run as a script (`scripts/parity_check.py`) that computes **in memory** and never
writes.
- Indicators: for 25 random active listings, compute `compute_ta_frame` over the migrated 1d bars
  and compare against the `legacy-vinzo-core` `ta_daily` rows for the last 60 dates, column by
  column, using `numpy.isclose(rtol=1e-9, atol=1e-9)` (relative tolerance, so `obv` is fine). Every
  indicator value depends only on bars up to its own date, so identical bars give identical values.
- HVB: re-evaluate the last 60 sessions for every active listing and compare the set of
  `(listing, as_of)` hits with the legacy `HIGH_VOLUME_BUY` rows in that window.
- **Gate:** at least 99% of compared values and hits must match. Mismatches are listed in the report
  with the bar dates; a legacy row computed before Yahoo revised a bar is an acceptable difference.
  Below 99% stops the rollout before step 3 of §8.

### 6. Dependencies

Add `yfinance`, `pandas` and `numpy` to both `market-ingestion` and `analytics-worker`, pinned to
the versions vinzo-core used (`yfinance==1.8.0`, `pandas==3.1.1`, `numpy==2.5.4`) so the parity
holds.

### 7. Tests

- Unit tests: validation, gap detection, normalization, the indicator formulas (against values
  computed by vinzo-core's functions on a fixed frame) and the HVB rule.
- Recorded Yahoo responses in `services/market-ingestion/tests/fixtures/`. Tests never hit the
  network.
- Integration tests in `tests/integration/` against the local TimescaleDB. They cover the migration
  on a small seeded legacy dataset (counts and values preserved, guard raises on mismatch), `eod`
  with a fake provider (raw, bars, runs and gaps written; idempotent when re-run), `indicators` and
  `high-volume-buy`.

### 8. Rollout

1. **Backup:** a full `pg_dump -Fc` of the dev DB, saved under `data/raw/backups/` (git-ignored) and
   checked with `pg_restore --list`.
2. **Rehearsal:** restore the dump into the local DB, run `make migrate`, run `sync-reference`, run
   the parity tests, then run `eod`, `indicators`, `high-volume-buy` and `freshness` for real
   against Yahoo for a handful of listings.
3. **Stop the old cron** on the dev server (remove the `# >>> vinzo-core >>>` crontab block).
4. **Migrate the dev DB:** `make migrate` with `DATABASE_URL` pointing at dev, then `sync-reference`.
   Verify per-table row counts (legacy against new), 278 rows in `ohlcv_latest`, and `/health/ready`.
5. **Deploy and schedule:** put the new code on the dev server at `/home/admin/vynzo` and install
   `infra/cron/crontab`. Remove its "NOT INSTALLED YET" note.
6. **First live run:** run the chain by hand once, then let cron take over.
7. **Drop legacy:** show the user the verification report. Apply the `pending/…12`–`…15` drop files only after they say
   yes.

**Rollback:**
- **Before step 7:** the down migrations drop the new tables (`…11`→`…08` empty them, `…07` drops
  them and moves `legacy.*` back to `public`, `…06` drops the identity tables, including anything
  `sync-reference` added).
- **Data written after cutover is not carried back.** That's at most a few days of EOD bars, which
  the restored old cron re-fetches.
- **After step 7:** restore from the step 1 dump.

## Calls made by Claude (please check)

- Keeping table names (`ohlcv_1d` …) rather than renaming, so the API and docs vocabulary is unchanged.
- Parking old tables in a `legacy` schema rather than dropping them in the same migration.
- `NIFTY` modelled as a listing with `kind = 'index'` and no company.
- ISIN stored on `companies`.
- Legacy provenance label `legacy-vinzo-core`. New versions are `ta-1` and `hvb-1`.
- `eod` failure threshold of 10%.
- Yahoo adapter placed under `providers/vendor/`.
- Larger chunk intervals on the new tables, and the copy split into one migration per large table.
- After cutover, the pipeline may refresh bars and indicators in the recent window, including
  migrated ones.
- `sync-reference` creates NSE listings only. It doesn't create BSE listings, and it adds no provider
  symbols for inactive listings.
- Parity gate: 99% match at rtol/atol 1e-9, checked in memory.
- Rollback before the drop discards anything written after cutover.

## Left to the builder

Module internals; SQL for the copy (batching if a single `INSERT … SELECT` is too slow on 1M rows);
thread-pool details; log format; how fixtures are recorded.
