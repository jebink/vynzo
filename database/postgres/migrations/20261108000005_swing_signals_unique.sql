-- migrate:up
-- Baseline carried over from vinzo-core (idempotent: safe on a database that already has it).

-- One swing signal per symbol/exchange/bar. Earlier runs inserted a new row every time.
-- Idempotent: safe to run more than once.


-- Keep the most recent row for each (symbol, exchange, as_of)
DELETE FROM swing_signals s
USING swing_signals newer
WHERE s.symbol = newer.symbol
  AND s.exchange = newer.exchange
  AND s.as_of = newer.as_of
  AND s.id < newer.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_swing_signals_symbol_exchange_asof
    ON swing_signals (symbol, exchange, as_of);


-- migrate:down
-- Baseline migration: no automatic rollback. Restore from backup instead (docs/runbooks/backup-restore.md).
