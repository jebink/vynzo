-- migrate:up
-- Baseline carried over from vinzo-core (idempotent: safe on a database that already has it).

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Daily OHLCV bars for NSE/BSE symbols
CREATE TABLE IF NOT EXISTS ohlcv_daily (
    ts          TIMESTAMPTZ       NOT NULL,
    symbol      TEXT              NOT NULL,
    exchange    TEXT              NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    open        DOUBLE PRECISION  NOT NULL,
    high        DOUBLE PRECISION  NOT NULL,
    low         DOUBLE PRECISION  NOT NULL,
    close       DOUBLE PRECISION  NOT NULL,
    volume      BIGINT            NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, exchange, ts)
);

SELECT create_hypertable('ohlcv_daily', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_symbol_exchange_ts
    ON ohlcv_daily (symbol, exchange, ts DESC);

-- Convenience view: latest bar per symbol/exchange
CREATE OR REPLACE VIEW ohlcv_latest AS
SELECT DISTINCT ON (symbol, exchange)
    ts, symbol, exchange, open, high, low, close, volume
FROM ohlcv_daily
ORDER BY symbol, exchange, ts DESC;

-- migrate:down
-- Baseline migration: no automatic rollback. Restore from backup instead (docs/runbooks/backup-restore.md).
