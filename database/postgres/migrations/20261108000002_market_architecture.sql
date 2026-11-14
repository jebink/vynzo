-- migrate:up
-- Baseline carried over from vinzo-core (idempotent: safe on a database that already has it).

-- Market data architecture: raw OHLCV + aggregated timeframes
-- Run against: market database on TimescaleDB

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Shared enum-like checks via domain
DO $$ BEGIN
  CREATE DOMAIN exchange_code AS TEXT CHECK (VALUE IN ('NSE', 'BSE'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- Raw / stored bars per timeframe (separate hypertables for retention)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ohlcv_1m (
    ts          TIMESTAMPTZ      NOT NULL,
    symbol      TEXT             NOT NULL,
    exchange    exchange_code    NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      BIGINT           NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, exchange, ts)
);
SELECT create_hypertable('ohlcv_1m', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ohlcv_5m (LIKE ohlcv_1m INCLUDING ALL);
SELECT create_hypertable('ohlcv_5m', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ohlcv_15m (LIKE ohlcv_1m INCLUDING ALL);
SELECT create_hypertable('ohlcv_15m', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ohlcv_75m (LIKE ohlcv_1m INCLUDING ALL);
SELECT create_hypertable('ohlcv_75m', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ohlcv_1d (LIKE ohlcv_1m INCLUDING ALL);
SELECT create_hypertable('ohlcv_1d', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ohlcv_1w (LIKE ohlcv_1m INCLUDING ALL);
SELECT create_hypertable('ohlcv_1w', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ohlcv_1mo (LIKE ohlcv_1m INCLUDING ALL);
SELECT create_hypertable('ohlcv_1mo', 'ts', if_not_exists => TRUE);

-- Indexes for symbol lookups
CREATE INDEX IF NOT EXISTS idx_ohlcv_1m_sym  ON ohlcv_1m  (symbol, exchange, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_5m_sym  ON ohlcv_5m  (symbol, exchange, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_15m_sym ON ohlcv_15m (symbol, exchange, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_75m_sym ON ohlcv_75m (symbol, exchange, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_1d_sym  ON ohlcv_1d  (symbol, exchange, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_1w_sym  ON ohlcv_1w  (symbol, exchange, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_1mo_sym ON ohlcv_1mo (symbol, exchange, ts DESC);

-- ---------------------------------------------------------------------------
-- Retention (optimal holding-period config)
-- 1m: 90d | 5m: 1y | 15m: 2y | 75m: 5y | 1d/1w/1mo: keep (no drop)
-- ---------------------------------------------------------------------------
SELECT add_retention_policy('ohlcv_1m',  INTERVAL '90 days',  if_not_exists => TRUE);
SELECT add_retention_policy('ohlcv_5m',  INTERVAL '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('ohlcv_15m', INTERVAL '730 days', if_not_exists => TRUE);
SELECT add_retention_policy('ohlcv_75m', INTERVAL '1825 days', if_not_exists => TRUE);
-- daily / weekly / monthly: maximum retention (no policy)

-- ---------------------------------------------------------------------------
-- Ingestion audit: validation / gaps / runs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_runs (
    id           BIGSERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    symbol       TEXT NOT NULL,
    exchange     exchange_code NOT NULL,
    timeframe    TEXT NOT NULL,
    rows_upserted INTEGER NOT NULL DEFAULT 0,
    gaps_found   INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'running',
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS ohlcv_gaps (
    id           BIGSERIAL PRIMARY KEY,
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol       TEXT NOT NULL,
    exchange     exchange_code NOT NULL,
    timeframe    TEXT NOT NULL,
    gap_start    TIMESTAMPTZ NOT NULL,
    gap_end      TIMESTAMPTZ NOT NULL,
    resolved     BOOLEAN NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- Technical analysis cache (optional materialization)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ta_daily (
    ts           TIMESTAMPTZ NOT NULL,
    symbol       TEXT NOT NULL,
    exchange     exchange_code NOT NULL,
    rsi_14       DOUBLE PRECISION,
    ema_9        DOUBLE PRECISION,
    ema_21       DOUBLE PRECISION,
    ema_50       DOUBLE PRECISION,
    ema_200      DOUBLE PRECISION,
    macd         DOUBLE PRECISION,
    macd_signal  DOUBLE PRECISION,
    macd_hist    DOUBLE PRECISION,
    atr_14       DOUBLE PRECISION,
    vwap         DOUBLE PRECISION,
    PRIMARY KEY (symbol, exchange, ts)
);
SELECT create_hypertable('ta_daily', 'ts', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Swing trading signals
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swing_signals (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    as_of         TIMESTAMPTZ NOT NULL,
    symbol        TEXT NOT NULL,
    exchange      exchange_code NOT NULL,
    signal        TEXT NOT NULL CHECK (signal IN ('BUY', 'SELL', 'HOLD', 'WATCH')),
    entry         DOUBLE PRECISION,
    stop_loss     DOUBLE PRECISION,
    target_1      DOUBLE PRECISION,
    target_2      DOUBLE PRECISION,
    risk_reward   DOUBLE PRECISION,
    rationale     TEXT,
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_swing_signals_sym ON swing_signals (symbol, exchange, as_of DESC);

-- Drop legacy single table if empty migration path needed (keep if exists with data)
-- ohlcv_daily from earlier install remains for compatibility; new code uses ohlcv_1d

-- migrate:down
-- Baseline migration: no automatic rollback. Restore from backup instead (docs/runbooks/backup-restore.md).
