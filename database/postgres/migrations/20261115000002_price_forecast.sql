-- migrate:up
-- Daily close forecasts per listing and model (analytics_worker forecast job, after the EOD chain).
-- `points` is [{date, close}] for the next sessions; `metrics` is the walk-forward score
-- ({mape, hit_rate, n}) the UI uses to pick and label the default model.
CREATE TABLE price_forecast (
    listing_id  BIGINT      NOT NULL REFERENCES listings (listing_id) ON DELETE CASCADE,
    model       TEXT        NOT NULL,
    as_of       DATE        NOT NULL,
    horizon     SMALLINT    NOT NULL CHECK (horizon > 0),
    points      JSONB       NOT NULL,
    metrics     JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (listing_id, model, as_of)
);

-- migrate:down
DROP TABLE price_forecast;
