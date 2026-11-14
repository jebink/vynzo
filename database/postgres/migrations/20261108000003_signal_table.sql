-- migrate:up
-- Baseline carried over from vinzo-core (idempotent: safe on a database that already has it).

-- Extensible market signals (HIGH_VOLUME_BUY first; more types later)
-- Run against: market database on TimescaleDB

CREATE TABLE IF NOT EXISTS signal (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    as_of         TIMESTAMPTZ NOT NULL,
    symbol        TEXT NOT NULL,
    exchange      exchange_code NOT NULL,
    signal_type   TEXT NOT NULL,
    strength      DOUBLE PRECISION,
    price         DOUBLE PRECISION,
    volume        BIGINT,
    avg_volume    DOUBLE PRECISION,
    rationale     TEXT,
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (symbol, exchange, signal_type, as_of)
);

CREATE INDEX IF NOT EXISTS idx_signal_type_asof
    ON signal (signal_type, as_of DESC);

CREATE INDEX IF NOT EXISTS idx_signal_sym
    ON signal (symbol, exchange, as_of DESC);

CREATE INDEX IF NOT EXISTS idx_signal_created
    ON signal (created_at DESC);

COMMENT ON TABLE signal IS
  'Generic signal store. signal_type examples: HIGH_VOLUME_BUY (more to follow).';

COMMENT ON COLUMN signal.strength IS
  'Type-specific score; for HIGH_VOLUME_BUY = volume / avg_volume.';

-- migrate:down
-- Baseline migration: no automatic rollback. Restore from backup instead (docs/runbooks/backup-restore.md).
