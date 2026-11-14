-- migrate:up
-- Legacy drop, step 1 of 4: drops legacy.ohlcv_1d.
-- IRREVERSIBLE. Kept in database/postgres/pending/ until the user approves the copy
-- verification (row counts legacy vs new, parity); see pending/README.md.
-- The drop is split into four migrations (each its own transaction) so that no single
-- transaction takes more locks than the dev lock table holds (~31k): dropping a hypertable
-- locks every chunk and its indexes and constraints, ~9-11 locks per chunk, and ohlcv_1d,
-- ta_daily and ohlcv_1w have ~1,870 chunks each. Rehearsed peaks: 12 = 20.6k, 13 = 16.9k,
-- 14 = 20.6k, 15 = 5.3k.
DROP TABLE legacy.ohlcv_1d;

-- migrate:down
DO $$
BEGIN
    RAISE EXCEPTION 'restore from backup: legacy data is gone';
END $$;
