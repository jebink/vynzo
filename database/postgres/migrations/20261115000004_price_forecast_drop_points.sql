-- migrate:up
-- The forward projection was removed from the chart; only the past-prediction line remains.
ALTER TABLE price_forecast DROP COLUMN points;

-- migrate:down
ALTER TABLE price_forecast ADD COLUMN points JSONB NOT NULL DEFAULT '[]';
