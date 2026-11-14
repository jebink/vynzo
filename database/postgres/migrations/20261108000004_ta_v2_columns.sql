-- migrate:up
-- Baseline carried over from vinzo-core (idempotent: safe on a database that already has it).

-- Extra TA columns for swing v2 factors
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS adx_14 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS plus_di_14 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS minus_di_14 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS rvol_20 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS donchian_high_20 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS donchian_low_20 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS donchian_high_55 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS bb_width DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS obv DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS ema200_slope_20 DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS extension_atr DOUBLE PRECISION;
ALTER TABLE ta_daily ADD COLUMN IF NOT EXISTS ret_126 DOUBLE PRECISION;

-- migrate:down
-- Baseline migration: no automatic rollback. Restore from backup instead (docs/runbooks/backup-restore.md).
