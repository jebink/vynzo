-- migrate:up
-- What each model would have predicted over the chart's past sessions ([{date, close}]),
-- stitched from forecasts made every `horizon` sessions: the line the actual price is compared to.
ALTER TABLE price_forecast ADD COLUMN history JSONB NOT NULL DEFAULT '[]';

-- migrate:down
ALTER TABLE price_forecast DROP COLUMN history;
