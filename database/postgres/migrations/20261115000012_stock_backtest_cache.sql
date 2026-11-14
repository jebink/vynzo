-- migrate:up
-- Finished per-stock backtests (API stock page), so a ~20 s run survives API restarts and is
-- shared by every API worker. One row per listing: a new bar or engine version replaces it.
CREATE TABLE stock_backtest_cache (
    listing_id   BIGINT      PRIMARY KEY REFERENCES listings (listing_id) ON DELETE CASCADE,
    last_bar     TIMESTAMPTZ NOT NULL,  -- newest daily bar the run saw
    version      TEXT        NOT NULL,  -- engine + outcome rule versions
    events       JSONB       NOT NULL,  -- the NDJSON stream: start, progress..., done
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- migrate:down
DROP TABLE stock_backtest_cache;
