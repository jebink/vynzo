-- migrate:up
-- Legacy drop, step 4 of 4: drops the remaining legacy tables and schema `legacy`.
-- IRREVERSIBLE. Kept in database/postgres/pending/ until the user approves the copy
-- verification (row counts legacy vs new, parity); see pending/README.md.
-- The drop is split into four migrations (each its own transaction) so that no single
-- transaction takes more locks than the dev lock table holds (~31k): dropping a hypertable
-- locks every chunk and its indexes and constraints, ~9-11 locks per chunk, and ohlcv_1d,
-- ta_daily and ohlcv_1w have ~1,870 chunks each. Rehearsed peaks: 12 = 20.6k, 13 = 16.9k,
-- 14 = 20.6k, 15 = 5.3k.
DROP TABLE legacy.ohlcv_1mo;
DROP TABLE legacy.ohlcv_1m;
DROP TABLE legacy.ohlcv_5m;
DROP TABLE legacy.ohlcv_15m;
DROP TABLE legacy.ohlcv_75m;
DROP TABLE legacy.ohlcv_daily;
DROP TABLE legacy.ingest_runs;
DROP TABLE legacy.ohlcv_gaps;
DROP TABLE legacy.signal;
DROP TABLE legacy.swing_signals;
-- Then the schema itself, with anything left in it (the legacy id sequences go with their
-- tables; the intraday retention jobs go with their hypertables).
DROP SCHEMA legacy CASCADE;

-- migrate:down
DO $$
BEGIN
    RAISE EXCEPTION 'restore from backup: legacy data is gone';
END $$;
