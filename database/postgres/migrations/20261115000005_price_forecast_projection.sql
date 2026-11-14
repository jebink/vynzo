-- migrate:up
-- Each model's projection past the last bar ([{date, close}], 365 sessions). Untested at that
-- range: the scored part is `history` (30-session forecasts).
ALTER TABLE price_forecast ADD COLUMN projection JSONB NOT NULL DEFAULT '[]';

-- migrate:down
ALTER TABLE price_forecast DROP COLUMN projection;
