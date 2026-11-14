# Identity Migration, EOD Ingestion and Daily Analytics: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move vinzo-core's ~2.3M legacy rows into a listing-keyed schema without re-fetching, then restore the daily pipeline (EOD → indicators → high-volume-buy → freshness) on new code.

**Architecture:** dbmate migrations add `companies`/`listings`/`provider_symbols`, park old tables in a `legacy` schema, create listing-keyed tables and copy data with count/sum guards. `market-ingestion` fills in its stub packages (Yahoo adapter → raw → normalize → validate → upsert). `analytics-worker` ports the indicator and HVB code verbatim and keys it by `listing_id`.

**Tech Stack:** Python 3.13, uv workspace, psycopg 3, pandas/numpy/yfinance, PostgreSQL 16 + TimescaleDB 2.31, dbmate (Docker), pytest.

**Spec:** `docs/superpowers/specs/2026-11-11-identity-migration-and-ingestion-design.md`

## Global Constraints

- Migrations only in `database/postgres/migrations/`, dbmate format (`-- migrate:up` / `-- migrate:down`), named `20261111HHMMSS_<what>.sql`. Never edit `20261108000001`–`…05`.
- `drop_legacy` lives in `database/postgres/pending/` until the user approves. It must never sit in `migrations/` before then.
- Price and indicator columns stay `double precision`, volume stays `bigint`. Copies are `INSERT … SELECT`, with no casts or rounding.
- Pins in both `services/market-ingestion` and `services/analytics-worker`: `yfinance==1.8.0`, `pandas==3.1.1`, `numpy==2.5.4`.
- Provider name is `'yahoo'`. Legacy provenance is `calc_version = 'legacy-vinzo-core'`. New versions are `'ta-1'` and `'hvb-1'`.
- Daily-ingest timeframes are `1d`, `1w`, `1mo`. Overlaps are 7 / 21 / 45 days (1mo snapped to the 1st). Bar-final cutoff is 16:00 IST; freshness cutoff is 18:00 IST with one weekday of slack.
- `eod` exits 1 only when more than 10% of listings fail or there's a DB/config error.
- Tests never hit the network. The ported formulas must stay numerically identical to vinzo-core (reference copy, without `.env`, at `/private/tmp/claude-502/-Users-jebin-koshy-Desktop-vynzo/fa0c4b77-3cae-416f-90a7-c9846a55d34b/scratchpad/vinzo-core/market_data/`). Never extract the archive's `.env` into the repo.
- No git commits unless the user asks. Each task ends with its tests green, `uv run ruff check services tests scripts` clean and `uv run ruff format --check` clean.

## Review Focus

1. **Listing with zero bars** (newly activated, or a migrated listing that only has 1w data). `eod` must do a full-history fetch for it, not crash on `max(ts) IS NULL`. Test in Task 6.
2. **Yahoo returns an empty frame or NaN rows** (delisted, holiday, thin BSE history). The run is marked `ok` with 0 rows, no gap rows, and nothing written except the `ingest_runs` row. Test in Task 4 and Task 6.
3. **Re-running `eod` the same day.** It must be idempotent: the same bar count and no duplicate gaps. Raw rows do get appended again, which is intended because raw is an append-only log. Test in Task 6.
4. **Today's still-forming daily bar fetched before 16:00 IST.** Validation drops bars after the last complete session. Test in Task 4.
5. **Indicators with fewer than 200 bars** (EMA200 and ret_126 come out NaN). Those must be stored as SQL `NULL`, not NaN, and the job must not skip the listing. Test in Task 7.

---

### Task 1: Test harness and migrate script fix

**Files:**
- Modify: `scripts/migrate.sh` (only source `.env` when `DATABASE_URL` is unset)
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_harness.py`

**Interfaces:**
- Produces: pytest fixture `fresh_db(request) -> str` (URL of a new empty database `vynzo_test_<hex8>` on the local server, dropped at teardown). Helper `apply_migrations(url: str, *, until: str | None = None, include_pending: bool = False) -> list[str]` applies `-- migrate:up` sections in filename order, up to and including the file whose name starts with `until`, and returns the applied versions. It honours `-- migrate:up transaction:false` by using autocommit. Admin URL is the `DATABASE_URL` from repo `.env` with dbname swapped to `postgres`.

- [ ] **Step 1:** Write `test_baseline_migrations_apply`: on `fresh_db`, `apply_migrations(url, until="20261108000005")` returns 5 versions and `to_regclass('public.ohlcv_1d')` is not null.
- [ ] **Step 2:** Run `uv run pytest tests/integration/test_harness.py -v`. Expected: FAIL (fixture missing).
- [ ] **Step 3:** Implement the conftest. Split each file on the line `-- migrate:down` and execute the up part.
- [ ] **Step 4:** Change `migrate.sh` so it keeps a pre-set `DATABASE_URL`: `[[ -z "${DATABASE_URL:-}" && -f "$ROOT/.env" ]] && …`. Verify with `DATABASE_URL=postgresql://x:y@localhost:1/z scripts/migrate.sh status`, which must fail connecting to port 1 and not to `market`.
- [ ] **Step 5:** Run the test. Expected: PASS.

### Task 2: Identity and listing-keyed schema (migrations 06 and 07)

**Files:**
- Create: `database/postgres/migrations/20261111000006_instrument_identity.sql`
- Create: `database/postgres/migrations/20261111000007_park_legacy_and_create_tables.sql`
- Test: `tests/integration/test_migration_schema.py`

**Interfaces:**
- Produces: the tables and columns exactly as in spec §1–§2, including `raw_eod_bars(id bigserial, ingest_run_id bigint, provider text, provider_symbol text, timeframe text, bar_ts timestamptz, payload jsonb, fetched_at timestamptz default now())`, a hypertable on `fetched_at` with PK `(id, fetched_at)`. Chunk intervals: `ohlcv_1d`/`ta_daily` 365 d, `ohlcv_1w`/`ohlcv_1mo` 3650 d, intraday 7 d. Retention on 1m/5m/15m/75m: 90/365/730/1825 d. View `ohlcv_latest(listing_id, ts, open, high, low, close, volume)`. Migration 07's down moves `legacy.*` back to `public` and recreates the old view.

- [ ] **Step 1:** Write the tests. `seed_legacy(url)` inserts a fixture into the baseline tables: RELIANCE/NSE with 3 `ohlcv_1d` bars, 2 `ta_daily` rows, 1 `signal` HIGH_VOLUME_BUY, 1 `swing_signals`, 1 `ingest_runs` and 1 `ohlcv_gaps`; INFY/BSE with 1 `ohlcv_1w` bar; NIFTY/NSE with 1 `ohlcv_1d` bar. Then apply up to `…07`. Assertions:
  - `test_listings_created_from_legacy`: 3 listings, all `is_active`. NIFTY has `kind='index'`; the others are `'equity'`. All have `company_id IS NULL`.
  - `test_provider_symbols`: `{'RELIANCE.NS','INFY.BO','^NSEI'}`, all with `provider='yahoo'`.
  - `test_legacy_parked`: `legacy.ohlcv_1d` has 4 rows, and `public.ohlcv_1d` exists and is empty. `public.ohlcv_daily` does not exist.
  - `test_chunk_intervals`: `timescaledb_information.dimensions` shows 365 days for `ohlcv_1d`.
- [ ] **Step 2:** Run `uv run pytest tests/integration/test_migration_schema.py -v`. Expected: FAIL.
- [ ] **Step 3:** Write 06 and 07. Parking uses `ALTER TABLE public.X SET SCHEMA legacy` for all 13 tables and `ALTER SEQUENCE … SET SCHEMA legacy` for the 4 sequences. Listings come from a `UNION` of `(symbol, exchange)` across all 11 symbol-bearing legacy tables. NIFTY's provider symbol is `'^NSEI'`.
- [ ] **Step 4:** Run the tests. Expected: PASS. Also test the down path: `test_down_restores_legacy` runs the 07 down section and checks that `public.ohlcv_1d` holds the 4 legacy rows again.

### Task 3: Copy migrations 08–11 with guards, plus pending drop

**Files:**
- Create: `database/postgres/migrations/20261111000008_copy_ohlcv_1d.sql`, `…09_copy_ta_daily.sql`, `…10_copy_ohlcv_1w_1mo.sql`, `…11_copy_small_tables.sql`
- Create: `database/postgres/pending/20261111000012_drop_legacy.sql` and `database/postgres/pending/README.md` ("move into ../migrations only after approval")
- Modify: `database/postgres/README.md` (document 06–11 and pending/)
- Test: `tests/integration/test_migration_copy.py`

**Interfaces:**
- Consumes: Task 2 tables. Produces fully populated new tables. `ta_daily`, `signal` and `swing_signals` rows get `calc_version='legacy-vinzo-core'`. `ingest_runs.provider` is `'yahoo'`. Ids are preserved and sequences are `setval`'d to the max id.
- Guard (copy in every copy migration): a `DO $$ … $$` that raises `'copy mismatch: %'` when `count(*)` differs between `legacy.X` and `public.X`, or, for ohlcv tables, when `sum(close)` or `sum(volume)` differs. Compare with `IS DISTINCT FROM` so NULL-vs-NULL on empty tables counts as equal.

- [ ] **Step 1:** Write the tests using the Task 2 seed, applying all migrations:
  - `test_values_identical`: for every seeded row, the new row joined via listings equals the legacy row on every column, using exact `=` on floats.
  - `test_ids_and_sequences`: the `signal` id is preserved, and the next `nextval` is greater than the max id.
  - `test_provenance_labels`: every row in `ta_daily`, `signal` and `swing_signals` is `'legacy-vinzo-core'`.
  - `test_guard_raises`: after applying through 07, insert a legacy `ohlcv_1d` row whose `(symbol, exchange)` has no listing, then apply 08. It raises `copy mismatch`.
  - `test_empty_db_noop`: `fresh_db`, apply all. Succeeds with every table empty.
  - `test_pending_not_applied`: `apply_migrations(url)` without `include_pending` leaves `legacy` present; with `include_pending=True` it is gone.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Write 08–11 and the pending drop. Each down section is a `TRUNCATE` of its target tables.
- [ ] **Step 4:** Run `uv run pytest tests/integration -v`. Expected: PASS.

### Task 4: Ingestion core: provider, normalize, validate, gaps, sessions

**Files:**
- Modify: `services/market-ingestion/pyproject.toml` (add pins, plus `pandas` and `numpy`)
- Modify: `services/market-ingestion/src/market_ingestion/providers/base.py`
- Create: `.../providers/vendor/yahoo.py`, `.../timeframes.py`, `.../sessions.py`, `.../normalization/bars.py`, `.../validation/bars.py`, `.../recovery/gaps.py`
- Create: `services/market-ingestion/tests/fixtures/yahoo_reliance_1d.json` (a recorded frame: 10 bars including one NaN row and one bar with high<low, as `{"index":[iso…],"Open":[…],…}`)
- Test: `services/market-ingestion/tests/test_core.py`

**Interfaces:**
- `RawRecord(provider: str, provider_symbol: str, timeframe: str, bar_ts: datetime, payload: dict[str, Any])`, frozen. `bar_ts` is tz-aware UTC.
- `Provider` Protocol: `name: str`; `fetch_bars(provider_symbol: str, timeframe: str, start: date | None, end: date) -> list[RawRecord]`. `start=None` means full history.
- `YahooProvider(download: Callable[..., pd.DataFrame] | None = None)` with `name = "yahoo"`. `download` defaults to a wrapper around `yf.download` with the `Ticker(t).history()` same-ticker retry. Ported from vinzo-core `provider.fetch_ohlcv` (kwargs, lookback clamp, UTC index, start/end filter).
- `timeframes.py`: `TIMEFRAMES: dict[str, Timeframe]` where `Timeframe(key, table, yahoo_interval, overlap: timedelta | None)`, covering the 7 keys. `EOD_TIMEFRAMES = ("1d", "1w", "1mo")`.
- `sessions.py`: `last_complete_session(now: datetime) -> date`, `expected_latest_session(now: datetime) -> date`, `prev_weekday(d: date) -> date` (ported).
- `Bar(listing_id: int, ts: datetime, open: float, high: float, low: float, close: float, volume: int)`, frozen. `normalize(records: Iterable[RawRecord], listing_id: int) -> list[Bar]` skips records whose payload has a NaN or missing O/H/L/C/V.
- `validate_bars(bars: list[Bar], last_session: date) -> list[Bar]` drops OHLC-inconsistent bars, volume<0 and `ts.date() > last_session` (in IST); dedupes by ts keeping the last; returns them sorted.
- `detect_gaps(ts: list[datetime], timeframe: str) -> list[tuple[datetime, datetime]]` is ported verbatim, including the 1d ≤4-day skip.

- [ ] **Step 1:** Write the tests:
  - `test_yahoo_parses_fixture`: `YahooProvider(download=lambda *a, **k: frame_from_fixture())` → 10 RawRecords, all `bar_ts.tzinfo == UTC`, payload keys `{"Open","High","Low","Close","Volume"}`.
  - `test_yahoo_empty_frame`: download returns an empty DataFrame → `[]`.
  - `test_normalize_skips_nan` → 9 bars.
  - `test_validate_drops_bad_and_future`: the high<low bar is dropped; a bar dated today at 10:00 IST with `last_session` = yesterday is dropped; duplicate ts keeps the last.
  - `test_gaps_daily_skips_weekend`: Fri→Mon gives none; a 10-day hole gives one.
  - `test_last_complete_session`: 15:59 IST Wednesday gives Tuesday; 16:00 IST gives Wednesday.
  - `test_expected_latest_session_weekend`: Sunday gives Friday.
- [ ] **Step 2:** Run `uv sync --all-packages && uv run pytest services/market-ingestion -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the modules.
- [ ] **Step 4:** Run the tests. Expected: PASS.

### Task 5: Ingestion persistence and instruments

**Files:**
- Create: `.../market_ingestion/db.py`, `.../publisher/store.py`, `.../checkpoint/store.py`, `.../instruments/registry.py`, `.../instruments/reference.py`
- Test: `tests/integration/test_ingestion_store.py`

**Interfaces:**
- `db.connect(url: str) -> psycopg.Connection` uses `row_factory=dict_row` and `autocommit=False`.
- `ActiveListing(listing_id: int, exchange: str, symbol: str, provider_symbol: str)`. `active_listings(conn, provider: str = "yahoo") -> list[ActiveListing]` returns active listings that have a provider symbol, ordered by exchange then symbol. `find_listing(conn, exchange: str, symbol: str) -> ActiveListing | None`.
- `last_bar_ts(conn, listing_id: int, timeframe: str) -> datetime | None`. `fetch_start(timeframe: str, last_ts: datetime | None) -> date | None` returns `None` for full history; otherwise `last_ts.date() - overlap`, with 1mo snapped to day 1.
- `start_run(conn, listing_id, provider, timeframe) -> int`. `finish_run(conn, run_id, *, rows: int, gaps: int, status: str, notes: str | None = None) -> None`. `insert_raw(conn, run_id: int, records: list[RawRecord]) -> int`. `upsert_bars(conn, timeframe: str, bars: list[Bar]) -> int` uses `ON CONFLICT (listing_id, ts) DO UPDATE`. `record_gaps(conn, listing_id, timeframe, gaps) -> int` skips gaps already recorded with the same `(listing_id, timeframe, gap_start, gap_end)`.
- `SyncReport(companies_upserted: int, listings_created: int, listings_linked: int, unlinked_bse: list[str])`. `sync_reference(conn, nse_csv: Path, bse_csv: Path) -> SyncReport` behaves as in spec §3 step 5. Note that the CSV headers have leading spaces (`" ISIN NUMBER"`, `" SERIES"`, `" DATE OF LISTING"` as `DD-MON-YYYY`), so strip them.

- [ ] **Step 1:** Write the tests on `fresh_db` with all migrations applied:
  - `test_upsert_bars_idempotent`: upserting the same 3 bars twice leaves 3 rows; a changed close updates the row.
  - `test_raw_append_only`: inserting the same records twice gives 2× rows.
  - `test_record_gaps_dedup`.
  - `test_fetch_start`: `None` → `None`; 1d is 7 days back; 1mo is snapped to the 1st.
  - `test_sync_reference`: seed listings RELIANCE/NSE (active, from migration) and INFY/BSE; a tiny CSV pair (RELIANCE and INFY in NSE, INFY in BSE). Afterwards RELIANCE and INFY/BSE are linked to the right company, a new INFY/NSE listing is created with `is_active=false` and no provider symbol, and re-running changes nothing (`listings_created == 0`).
  - `test_active_listings_excludes_inactive`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.

### Task 6: Ingestion jobs (eod, backfill, freshness, sync-reference)

**Files:**
- Create: `.../market_ingestion/pipeline.py`, `.../market_ingestion/freshness.py`
- Modify: `.../market_ingestion/__main__.py`, `.../market_ingestion/config.py` (add `kuma_push_url: str | None = None`, `workers: int = 4`)
- Modify: `services/market-ingestion/tests/test_cli.py`
- Test: `tests/integration/test_eod.py`

**Interfaces:**
- `TimeframeResult(listing_id, timeframe, rows: int, gaps: int, status: str, error: str | None)`.
- `ingest_listing(conn, provider: Provider, listing: ActiveListing, timeframe: str, end: date) -> TimeframeResult` runs in one transaction per call: start_run, fetch, insert_raw, normalize, validate, upsert, gaps, finish_run. On an exception it rolls back, writes `finish_run(status="error", notes=str(exc)[:300])` in a new transaction, and returns status `"error"`.
- `EodReport(listings: int, failed: list[str], rows: int)`. `run_eod(db_url: str, provider: Provider, *, workers: int = 4, now: datetime | None = None, only: list[ActiveListing] | None = None) -> EodReport` uses one connection per worker thread, iterates timeframes in `EOD_TIMEFRAMES` order, and counts a listing as failed if any of its timeframes failed.
- `run_backfill(db_url, provider, *, listing: str | None = None, now=None) -> EodReport` handles unresolved gaps: it fetches `[gap_start, gap_end]`, sets `resolved=true` if bars now exist strictly inside the gap, and runs full history for active listings with no bars in a timeframe. `listing` uses the format `"NSE:RELIANCE"`.
- `FreshnessResult(fresh: bool, latest: date | None, expected: date, pushed: bool | None)`. `check_freshness(conn, *, now: datetime | None = None, push_url: str | None = None) -> FreshnessResult`.
- CLI: `python -m market_ingestion {eod,backfill,freshness,sync-reference} [--listing EXCH:SYM]`. Exit codes: eod/backfill exit 1 if `len(failed) > 0.1 * listings`; freshness exits 1 if stale; sync-reference reads `REPO_ROOT/data/reference/{nse_equities,bse_all_equities}.csv`. Each job logs one JSON summary line.

- [ ] **Step 1:** Write the tests with `FakeProvider`, whose `fetch_bars` returns canned RawRecords per `(provider_symbol, timeframe)`, records each `start` it was called with, and raises for a symbol named `BOOM.NS`:
  - `test_eod_writes_everything`: seeded RELIANCE with a 1d bar on 2026-11-05; `now` = 2026-11-11 17:00 IST. The fake was called with start 2026-10-29 for 1d. New bars are upserted, raw rows are inserted, an `ingest_runs` row has status ok and provider yahoo.
  - `test_eod_full_history_for_new_listing`: listing with no bars → `start=None`.
  - `test_eod_empty_response_ok`: 0 rows, status ok, no gaps.
  - `test_eod_idempotent`: two runs give the same bar count.
  - `test_eod_isolates_failure`: BOOM fails while RELIANCE succeeds; `report.failed == ["NSE:BOOM"]`; BOOM's run row has status error.
  - `test_eod_exit_code_threshold` (CLI with monkeypatched `run_eod`): 1 failure out of 20 exits 0; 3 out of 20 exits 1.
  - `test_backfill_resolves_gap`: seeded bars on 11-02 and 11-14 plus an unresolved `ohlcv_gaps` row covering them; the fake returns bars for 11-03 through 11-13. Afterwards the gap is `resolved=true` and the bars exist. `test_backfill_listing_filter`: `listing="NSE:RELIANCE"` touches only that listing.
  - `test_freshness_stale_and_fresh`: latest bar Monday with `now` Wednesday 19:00 IST is stale; latest Tuesday is fresh.
  - Update `test_cli.py`: `set(JOBS) == {"eod","backfill","freshness","sync-reference"}`.
- [ ] **Step 2:** Run `uv run pytest tests/integration/test_eod.py services/market-ingestion -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. The Kuma push logic is ported from vinzo-core `daily.check_freshness`.
- [ ] **Step 4:** Run the tests. Expected: PASS.

### Task 7: Analytics: indicators and high-volume-buy

**Files:**
- Modify: `services/analytics-worker/pyproject.toml` (pins), `.../analytics_worker/__main__.py`
- Create: `.../analytics_worker/db.py`, `.../indicators/ta.py`, `.../indicators/job.py`, `.../signals/high_volume_buy.py`
- Create: `services/analytics-worker/tests/fixtures/ta_golden.csv` and `services/analytics-worker/tests/fixtures/make_golden.py`. The script builds a deterministic 300-bar frame (`numpy.random.default_rng(7)` random walk), runs vinzo-core's `compute_ta_frame` imported from the scratchpad path above, and writes the input and output columns.
- Test: `services/analytics-worker/tests/test_ta.py`, `tests/integration/test_analytics_jobs.py`

**Interfaces:**
- `ta.py` is a verbatim port of vinzo-core `indicators.py` functions: `compute_ta_frame(df: pd.DataFrame) -> pd.DataFrame` and `TA_COLUMNS: tuple[str, ...]` (22 names, same order).
- `db.load_daily_bars(conn, listing_id: int) -> pd.DataFrame` returns columns open/high/low/close/volume with a UTC ts index, sorted.
- `IndicatorsReport(listings: int, rows: int, failed: list[int])`. `run_indicators(conn, *, tail: int = 15, calc_version: str = "ta-1", listing_ids: list[int] | None = None) -> IndicatorsReport` selects active listings where `max(ohlcv_1d.ts) > coalesce(max(ta_daily.ts), '-infinity')` (or uses the given ids), computes over full history and upserts the last `tail` rows with `computed_at=now()`. NaN becomes NULL.
- `evaluate_at_index(df: pd.DataFrame, idx: int, *, lookback: int = 20, multiplier: float = 2.0) -> dict | None` returns keys `as_of, strength, price, volume, avg_volume, rationale, meta`, with the rationale string and meta keys exactly as in vinzo-core.
- `HvbReport(scanned: int, found: int, failed: list[int])`. `run_high_volume_buy(conn, *, days: int = 1, as_of: date | None = None, lookback: int = 20, multiplier: float = 2.0, calc_version: str = "hvb-1") -> HvbReport` upserts `signal` on `(listing_id, signal_type, as_of)` with `signal_type='HIGH_VOLUME_BUY'`.
- CLI: `python -m analytics_worker indicators` and `python -m analytics_worker high-volume-buy [--days N] [--as-of YYYY-MM-DD]`. Exit 1 if more than 10% of listings failed. `swing` and `sentiment` stay `NotImplementedError`.

- [ ] **Step 1:** Generate the golden file: `uv run python services/analytics-worker/tests/fixtures/make_golden.py`. Expected: `ta_golden.csv` with 300 rows.
- [ ] **Step 2:** Write the tests:
  - `test_ta_matches_vinzo_core`: every `TA_COLUMNS` column is `np.allclose(rtol=1e-12, atol=1e-12, equal_nan=True)` against the golden file.
  - `test_hvb_rule`: synthetic 21-bar frame with last bar volume 2.5× average and green/up → a hit with strength 2.5 and the rationale beginning `"High volume buy: vol "`; at 1.9× → `None`.
  - Integration: `test_indicators_short_history_nulls` (50 bars → 15 rows written, `ema_200 IS NULL`, `calc_version='ta-1'`).
  - Integration: `test_indicators_skips_up_to_date` (second run writes 0).
  - Integration: `test_hvb_upsert_idempotent` (`days=5` twice → same signal count).
- [ ] **Step 3:** Run `uv run pytest services/analytics-worker tests/integration/test_analytics_jobs.py -v`. Expected: FAIL.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run the tests. Expected: PASS. Then run the full suite `make test`. Expected: PASS.

### Task 8: Parity script, then local rehearsal on a dev snapshot

**Files:**
- Create: `scripts/parity_check.py`
- Modify: `infra/cron/crontab` (drop the "NOT INSTALLED YET" note), `docs/runbooks/` (new `identity-migration.md` recording the exact commands used)

**Interfaces:**
- `parity_check.py --db URL [--sample 25] [--window 60]` reads `public` bars and `legacy.ta_daily`/`legacy.signal` (so it needs the legacy schema present), uses `analytics_worker.indicators.ta.compute_ta_frame` and `evaluate_at_index` in memory, and prints per-check match rates and up to 20 mismatches. Exits 0 when both rates are ≥ 0.99.

- [ ] **Step 1: Backup.** Run `docker exec timescaledb pg_dump "$DEV_URL" -Fc -Z 6 > data/raw/backups/dev_market_<UTC stamp>.dump`, then `docker exec -i timescaledb pg_restore --list < file | head`. Expected: a TOC listing, and a file size greater than 50 MB.
- [ ] **Step 2: Restore into the local `market` database** (it currently has 0 rows; check again first). Stop the local API (`make api` background process) so it releases its pool connections, then drop and recreate `market`, `CREATE EXTENSION timescaledb`, `SELECT timescaledb_pre_restore()`, `pg_restore -d market --no-owner`, then `SELECT timescaledb_post_restore()`. Verify that row counts equal the dev counts in spec "Current state".
- [ ] **Step 3:** Run `make migrate`. Expected: …01–…05 are recorded and 06–11 applied without a guard error. Record the wall time of each copy. If it fails with `out of shared memory`, apply the spec §3 step 4 fallback.
- [ ] **Step 4:** Run `uv run python -m market_ingestion sync-reference`. Expected: about 2,370 listings created, 0 unlinked BSE.
- [ ] **Step 5:** Run `uv run python scripts/parity_check.py --db "$DATABASE_URL"`. Expected: both rates ≥ 0.99 and exit 0. **Below that, stop and report to the user.**
- [ ] **Step 6:** Run the live chain for real against Yahoo on 5 listings, then the full chain: `python -m market_ingestion eod && python -m analytics_worker indicators && python -m analytics_worker high-volume-buy && python -m market_ingestion freshness`. Expected: all exit 0 and `ohlcv_latest` has 278 rows.
- [ ] **Step 7:** Restart the local API with `make api`. Check `curl localhost:8000/health/ready` returns `{"status":"ok","db":"ok"}` and `curl -s -o /dev/null -w '%{http_code}' localhost:3000` returns `200`.

### Task 9: Dev-server cutover (needs SSH; blocked until the user grants access)

- [ ] **Step 1:** Take a fresh dev backup as in Task 8 Step 1, taken *after* the old cron's last run.
- [ ] **Step 2:** Over SSH, remove the `# >>> vinzo-core >>>` … `# <<< vinzo-core <<<` crontab block. Confirm with `crontab -l`.
- [ ] **Step 3:** From this Mac, run `DATABASE_URL="$DEV_URL" scripts/migrate.sh up`, then `DATABASE_URL="$DEV_URL" uv run python -m market_ingestion sync-reference`, then the parity check against dev. Expected: the same results as the rehearsal.
- [ ] **Step 4:** Deploy the repo to `/home/admin/vynzo` (rsync, excluding `.venv`, `node_modules`, `data/raw`, `.env`). Write the server `.env` with dev `DATABASE_URL`. Run `uv sync --all-packages --frozen`, then run the chain once by hand.
- [ ] **Step 5:** Run `crontab infra/cron/crontab` on the server, after merging with any non-vinzo entries already there.
- [ ] **Step 6:** Report to the user: per-table legacy vs new counts, parity rates, first-run results. **Ask for approval to drop legacy.** Only on a yes: move `pending/…12_drop_legacy.sql` into `migrations/`, apply it on dev and local, and run the full test suite.
