-- migrate:up
-- Park the vinzo-core tables (keyed by symbol + exchange) in schema `legacy`, create a listing
-- for every legacy (symbol, exchange), and create the new listing-keyed tables, empty.
-- Data is copied by 20261111000008..11. legacy.* stays intact until the pending drop migration.
--
-- Note: TimescaleDB retention jobs on the legacy intraday hypertables (1m/5m/15m/75m) stay
-- attached to the parked tables. Legacy is read-only from here until the drop.

-- ---------------------------------------------------------------------------
-- 1. Park legacy
-- ---------------------------------------------------------------------------
CREATE SCHEMA legacy;

DROP VIEW public.ohlcv_latest;

ALTER TABLE public.ohlcv_daily   SET SCHEMA legacy;
ALTER TABLE public.ohlcv_1m      SET SCHEMA legacy;
ALTER TABLE public.ohlcv_5m      SET SCHEMA legacy;
ALTER TABLE public.ohlcv_15m     SET SCHEMA legacy;
ALTER TABLE public.ohlcv_75m     SET SCHEMA legacy;
ALTER TABLE public.ohlcv_1d      SET SCHEMA legacy;
ALTER TABLE public.ohlcv_1w      SET SCHEMA legacy;
ALTER TABLE public.ohlcv_1mo     SET SCHEMA legacy;
ALTER TABLE public.ta_daily      SET SCHEMA legacy;
ALTER TABLE public.ingest_runs   SET SCHEMA legacy;
ALTER TABLE public.ohlcv_gaps    SET SCHEMA legacy;
ALTER TABLE public.signal        SET SCHEMA legacy;
ALTER TABLE public.swing_signals SET SCHEMA legacy;

-- The bigserial sequences are owned by their columns, so ALTER TABLE ... SET SCHEMA has already
-- moved them. IF EXISTS covers a database where a sequence lost its OWNED BY link.
ALTER SEQUENCE IF EXISTS public.ingest_runs_id_seq   SET SCHEMA legacy;
ALTER SEQUENCE IF EXISTS public.ohlcv_gaps_id_seq    SET SCHEMA legacy;
ALTER SEQUENCE IF EXISTS public.signal_id_seq        SET SCHEMA legacy;
ALTER SEQUENCE IF EXISTS public.swing_signals_id_seq SET SCHEMA legacy;

-- ---------------------------------------------------------------------------
-- 2. Listings and provider symbols from every legacy (symbol, exchange)
--    (ohlcv_daily is an unused leftover and is not a listing source)
-- ---------------------------------------------------------------------------
INSERT INTO listings (exchange, symbol, kind, is_active)
SELECT src.exchange::exchange_code,
       src.symbol,
       CASE WHEN src.exchange = 'NSE' AND src.symbol = 'NIFTY' THEN 'index' ELSE 'equity' END,
       true
FROM (
    SELECT symbol, exchange::text AS exchange FROM legacy.ohlcv_1m
    UNION SELECT symbol, exchange::text FROM legacy.ohlcv_5m
    UNION SELECT symbol, exchange::text FROM legacy.ohlcv_15m
    UNION SELECT symbol, exchange::text FROM legacy.ohlcv_75m
    UNION SELECT symbol, exchange::text FROM legacy.ohlcv_1d
    UNION SELECT symbol, exchange::text FROM legacy.ohlcv_1w
    UNION SELECT symbol, exchange::text FROM legacy.ohlcv_1mo
    UNION SELECT symbol, exchange::text FROM legacy.ta_daily
    UNION SELECT symbol, exchange::text FROM legacy.ingest_runs
    UNION SELECT symbol, exchange::text FROM legacy.ohlcv_gaps
    UNION SELECT symbol, exchange::text FROM legacy.signal
    UNION SELECT symbol, exchange::text FROM legacy.swing_signals
) AS src
ORDER BY src.exchange, src.symbol;

-- Matches vinzo-core provider.to_ticker for the legacy universe.
INSERT INTO provider_symbols (provider, provider_symbol, listing_id)
SELECT 'yahoo',
       CASE
           WHEN l.exchange = 'NSE' AND l.symbol = 'NIFTY' THEN '^NSEI'
           WHEN l.exchange = 'NSE' THEN l.symbol || '.NS'
           ELSE l.symbol || '.BO'
       END,
       l.listing_id
FROM listings l
ORDER BY l.listing_id;

-- ---------------------------------------------------------------------------
-- 3. Bars: same columns, listing_id replaces symbol + exchange. Prices stay double precision
--    and volume bigint, so values copy bit for bit.
-- ---------------------------------------------------------------------------
CREATE TABLE public.ohlcv_1m (
    ts          TIMESTAMPTZ      NOT NULL,
    listing_id  BIGINT           NOT NULL REFERENCES listings (listing_id),
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      BIGINT           NOT NULL DEFAULT 0,
    PRIMARY KEY (listing_id, ts)
);
CREATE TABLE public.ohlcv_5m  (LIKE public.ohlcv_1m INCLUDING ALL);
CREATE TABLE public.ohlcv_15m (LIKE public.ohlcv_1m INCLUDING ALL);
CREATE TABLE public.ohlcv_75m (LIKE public.ohlcv_1m INCLUDING ALL);
CREATE TABLE public.ohlcv_1d  (LIKE public.ohlcv_1m INCLUDING ALL);
CREATE TABLE public.ohlcv_1w  (LIKE public.ohlcv_1m INCLUDING ALL);
CREATE TABLE public.ohlcv_1mo (LIKE public.ohlcv_1m INCLUDING ALL);

-- LIKE does not copy foreign keys.
ALTER TABLE public.ohlcv_5m  ADD FOREIGN KEY (listing_id) REFERENCES listings (listing_id);
ALTER TABLE public.ohlcv_15m ADD FOREIGN KEY (listing_id) REFERENCES listings (listing_id);
ALTER TABLE public.ohlcv_75m ADD FOREIGN KEY (listing_id) REFERENCES listings (listing_id);
ALTER TABLE public.ohlcv_1d  ADD FOREIGN KEY (listing_id) REFERENCES listings (listing_id);
ALTER TABLE public.ohlcv_1w  ADD FOREIGN KEY (listing_id) REFERENCES listings (listing_id);
ALTER TABLE public.ohlcv_1mo ADD FOREIGN KEY (listing_id) REFERENCES listings (listing_id);

-- Intraday keeps 7-day chunks (retention drops whole chunks). Legacy used 7 days everywhere,
-- which over-chunks daily data.
SELECT create_hypertable('public.ohlcv_1m',  by_range('ts', INTERVAL '7 days'));
SELECT create_hypertable('public.ohlcv_5m',  by_range('ts', INTERVAL '7 days'));
SELECT create_hypertable('public.ohlcv_15m', by_range('ts', INTERVAL '7 days'));
SELECT create_hypertable('public.ohlcv_75m', by_range('ts', INTERVAL '7 days'));
SELECT create_hypertable('public.ohlcv_1d',  by_range('ts', INTERVAL '365 days'));
SELECT create_hypertable('public.ohlcv_1w',  by_range('ts', INTERVAL '3650 days'));
SELECT create_hypertable('public.ohlcv_1mo', by_range('ts', INTERVAL '3650 days'));

CREATE INDEX idx_ohlcv_1m_listing  ON public.ohlcv_1m  (listing_id, ts DESC);
CREATE INDEX idx_ohlcv_5m_listing  ON public.ohlcv_5m  (listing_id, ts DESC);
CREATE INDEX idx_ohlcv_15m_listing ON public.ohlcv_15m (listing_id, ts DESC);
CREATE INDEX idx_ohlcv_75m_listing ON public.ohlcv_75m (listing_id, ts DESC);
CREATE INDEX idx_ohlcv_1d_listing  ON public.ohlcv_1d  (listing_id, ts DESC);
CREATE INDEX idx_ohlcv_1w_listing  ON public.ohlcv_1w  (listing_id, ts DESC);
CREATE INDEX idx_ohlcv_1mo_listing ON public.ohlcv_1mo (listing_id, ts DESC);

-- Same retention as legacy. 1d/1w/1mo: no policy (kept forever).
SELECT add_retention_policy('public.ohlcv_1m',  INTERVAL '90 days');
SELECT add_retention_policy('public.ohlcv_5m',  INTERVAL '365 days');
SELECT add_retention_policy('public.ohlcv_15m', INTERVAL '730 days');
SELECT add_retention_policy('public.ohlcv_75m', INTERVAL '1825 days');

CREATE VIEW public.ohlcv_latest AS
SELECT DISTINCT ON (listing_id)
    listing_id, ts, open, high, low, close, volume
FROM public.ohlcv_1d
ORDER BY listing_id, ts DESC;

COMMENT ON VIEW public.ohlcv_latest IS 'Latest ohlcv_1d bar per listing.';

-- ---------------------------------------------------------------------------
-- 4. Raw provider payloads (architecture rule 2): append-only, never updated.
--    Migrated legacy bars have no raw records.
-- ---------------------------------------------------------------------------
CREATE TABLE public.raw_eod_bars (
    id              BIGSERIAL   NOT NULL,
    ingest_run_id   BIGINT      NOT NULL,
    provider        TEXT        NOT NULL,
    provider_symbol TEXT        NOT NULL,
    timeframe       TEXT        NOT NULL,
    bar_ts          TIMESTAMPTZ NOT NULL,
    payload         JSONB       NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, fetched_at)
);
SELECT create_hypertable('public.raw_eod_bars', by_range('fetched_at', INTERVAL '7 days'));

CREATE INDEX idx_raw_eod_bars_symbol
    ON public.raw_eod_bars (provider, provider_symbol, timeframe, bar_ts DESC);

COMMENT ON TABLE public.raw_eod_bars IS
  'Append-only log of provider bars exactly as returned (payload). Never updated. '
  'ingest_run_id refers to ingest_runs.id (no FK, so ingest_runs can be truncated on rollback).';

-- ---------------------------------------------------------------------------
-- 5. Indicators
-- ---------------------------------------------------------------------------
CREATE TABLE public.ta_daily (
    ts               TIMESTAMPTZ NOT NULL,
    listing_id       BIGINT      NOT NULL REFERENCES listings (listing_id),
    rsi_14           DOUBLE PRECISION,
    ema_9            DOUBLE PRECISION,
    ema_21           DOUBLE PRECISION,
    ema_50           DOUBLE PRECISION,
    ema_200          DOUBLE PRECISION,
    macd             DOUBLE PRECISION,
    macd_signal      DOUBLE PRECISION,
    macd_hist        DOUBLE PRECISION,
    atr_14           DOUBLE PRECISION,
    vwap             DOUBLE PRECISION,
    adx_14           DOUBLE PRECISION,
    plus_di_14       DOUBLE PRECISION,
    minus_di_14      DOUBLE PRECISION,
    rvol_20          DOUBLE PRECISION,
    donchian_high_20 DOUBLE PRECISION,
    donchian_low_20  DOUBLE PRECISION,
    donchian_high_55 DOUBLE PRECISION,
    bb_width         DOUBLE PRECISION,
    obv              DOUBLE PRECISION,
    ema200_slope_20  DOUBLE PRECISION,
    extension_atr    DOUBLE PRECISION,
    ret_126          DOUBLE PRECISION,
    calc_version     TEXT        NOT NULL,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (listing_id, ts)
);
SELECT create_hypertable('public.ta_daily', by_range('ts', INTERVAL '365 days'));

COMMENT ON COLUMN public.ta_daily.calc_version IS
  'Indicator code version (ta-1 ...). Migrated rows: legacy-vinzo-core.';

-- ---------------------------------------------------------------------------
-- 6. Ingestion audit
-- ---------------------------------------------------------------------------
CREATE TABLE public.ingest_runs (
    id            BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    listing_id    BIGINT      NOT NULL REFERENCES listings (listing_id),
    provider      TEXT        NOT NULL,
    timeframe     TEXT        NOT NULL,
    rows_upserted INTEGER     NOT NULL DEFAULT 0,
    gaps_found    INTEGER     NOT NULL DEFAULT 0,
    status        TEXT        NOT NULL DEFAULT 'running',
    notes         TEXT
);

CREATE TABLE public.ohlcv_gaps (
    id          BIGSERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    listing_id  BIGINT      NOT NULL REFERENCES listings (listing_id),
    timeframe   TEXT        NOT NULL,
    gap_start   TIMESTAMPTZ NOT NULL,
    gap_end     TIMESTAMPTZ NOT NULL,
    resolved    BOOLEAN     NOT NULL DEFAULT false
);

-- ---------------------------------------------------------------------------
-- 7. Signals
-- ---------------------------------------------------------------------------
CREATE TABLE public.signal (
    id           BIGSERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of        TIMESTAMPTZ NOT NULL,
    listing_id   BIGINT      NOT NULL REFERENCES listings (listing_id),
    signal_type  TEXT        NOT NULL,
    strength     DOUBLE PRECISION,
    price        DOUBLE PRECISION,
    volume       BIGINT,
    avg_volume   DOUBLE PRECISION,
    rationale    TEXT,
    meta         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    calc_version TEXT        NOT NULL,
    UNIQUE (listing_id, signal_type, as_of)
);

CREATE INDEX idx_signal_type_asof ON public.signal (signal_type, as_of DESC);
CREATE INDEX idx_signal_listing   ON public.signal (listing_id, as_of DESC);
CREATE INDEX idx_signal_created   ON public.signal (created_at DESC);

COMMENT ON TABLE public.signal IS
  'Generic signal store. signal_type examples: HIGH_VOLUME_BUY (more to follow).';
COMMENT ON COLUMN public.signal.strength IS
  'Type-specific score; for HIGH_VOLUME_BUY = volume / avg_volume.';
COMMENT ON COLUMN public.signal.calc_version IS
  'Detector code version (hvb-1 ...). Migrated rows: legacy-vinzo-core.';

CREATE TABLE public.swing_signals (
    id           BIGSERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of        TIMESTAMPTZ NOT NULL,
    listing_id   BIGINT      NOT NULL REFERENCES listings (listing_id),
    signal       TEXT        NOT NULL CHECK (signal IN ('BUY', 'SELL', 'HOLD', 'WATCH')),
    entry        DOUBLE PRECISION,
    stop_loss    DOUBLE PRECISION,
    target_1     DOUBLE PRECISION,
    target_2     DOUBLE PRECISION,
    risk_reward  DOUBLE PRECISION,
    rationale    TEXT,
    meta         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    calc_version TEXT        NOT NULL,
    UNIQUE (listing_id, as_of)
);

COMMENT ON COLUMN public.swing_signals.calc_version IS
  'Swing code version. Migrated rows: legacy-vinzo-core.';

-- migrate:down
-- Rollback before the legacy drop: discard the new tables (and anything written to them after
-- cutover), remove the listings this migration created, and move legacy.* back to public.
-- Listings created later by sync-reference stay until 20261111000006 down.

DROP VIEW IF EXISTS public.ohlcv_latest;
DROP TABLE IF EXISTS public.raw_eod_bars;
DROP TABLE IF EXISTS public.swing_signals;
DROP TABLE IF EXISTS public.signal;
DROP TABLE IF EXISTS public.ohlcv_gaps;
DROP TABLE IF EXISTS public.ingest_runs;
DROP TABLE IF EXISTS public.ta_daily;
DROP TABLE IF EXISTS public.ohlcv_1mo;
DROP TABLE IF EXISTS public.ohlcv_1w;
DROP TABLE IF EXISTS public.ohlcv_1d;
DROP TABLE IF EXISTS public.ohlcv_75m;
DROP TABLE IF EXISTS public.ohlcv_15m;
DROP TABLE IF EXISTS public.ohlcv_5m;
DROP TABLE IF EXISTS public.ohlcv_1m;

-- Same source set as the up section.
CREATE TEMP TABLE legacy_pairs AS
SELECT symbol, exchange::text AS exchange FROM legacy.ohlcv_1m
UNION SELECT symbol, exchange::text FROM legacy.ohlcv_5m
UNION SELECT symbol, exchange::text FROM legacy.ohlcv_15m
UNION SELECT symbol, exchange::text FROM legacy.ohlcv_75m
UNION SELECT symbol, exchange::text FROM legacy.ohlcv_1d
UNION SELECT symbol, exchange::text FROM legacy.ohlcv_1w
UNION SELECT symbol, exchange::text FROM legacy.ohlcv_1mo
UNION SELECT symbol, exchange::text FROM legacy.ta_daily
UNION SELECT symbol, exchange::text FROM legacy.ingest_runs
UNION SELECT symbol, exchange::text FROM legacy.ohlcv_gaps
UNION SELECT symbol, exchange::text FROM legacy.signal
UNION SELECT symbol, exchange::text FROM legacy.swing_signals;

DELETE FROM provider_symbols ps
USING listings l, legacy_pairs p
WHERE ps.listing_id = l.listing_id
  AND l.exchange::text = p.exchange
  AND l.symbol = p.symbol;

DELETE FROM listings l
USING legacy_pairs p
WHERE l.exchange::text = p.exchange
  AND l.symbol = p.symbol;

DROP TABLE legacy_pairs;

ALTER TABLE legacy.ohlcv_daily   SET SCHEMA public;
ALTER TABLE legacy.ohlcv_1m      SET SCHEMA public;
ALTER TABLE legacy.ohlcv_5m      SET SCHEMA public;
ALTER TABLE legacy.ohlcv_15m     SET SCHEMA public;
ALTER TABLE legacy.ohlcv_75m     SET SCHEMA public;
ALTER TABLE legacy.ohlcv_1d      SET SCHEMA public;
ALTER TABLE legacy.ohlcv_1w      SET SCHEMA public;
ALTER TABLE legacy.ohlcv_1mo     SET SCHEMA public;
ALTER TABLE legacy.ta_daily      SET SCHEMA public;
ALTER TABLE legacy.ingest_runs   SET SCHEMA public;
ALTER TABLE legacy.ohlcv_gaps    SET SCHEMA public;
ALTER TABLE legacy.signal        SET SCHEMA public;
ALTER TABLE legacy.swing_signals SET SCHEMA public;

ALTER SEQUENCE IF EXISTS legacy.ingest_runs_id_seq   SET SCHEMA public;
ALTER SEQUENCE IF EXISTS legacy.ohlcv_gaps_id_seq    SET SCHEMA public;
ALTER SEQUENCE IF EXISTS legacy.signal_id_seq        SET SCHEMA public;
ALTER SEQUENCE IF EXISTS legacy.swing_signals_id_seq SET SCHEMA public;

DROP SCHEMA legacy;

-- Old view, as in 20261108000001.
CREATE VIEW public.ohlcv_latest AS
SELECT DISTINCT ON (symbol, exchange)
    ts, symbol, exchange, open, high, low, close, volume
FROM public.ohlcv_daily
ORDER BY symbol, exchange, ts DESC;
