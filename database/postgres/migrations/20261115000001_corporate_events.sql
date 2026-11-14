-- migrate:up
-- Upcoming corporate events per listing (market_ingestion events job, daily from Yahoo Finance).
-- A run replaces a listing's rows, so a moved date never leaves a stale duplicate behind.
CREATE TABLE corporate_event (
    listing_id  BIGINT      NOT NULL REFERENCES listings (listing_id) ON DELETE CASCADE,
    event_type  TEXT        NOT NULL CHECK (event_type IN ('results', 'ex_dividend')),
    event_date  DATE        NOT NULL,
    details     JSONB       NOT NULL DEFAULT '{}',
    source      TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (listing_id, event_type, event_date)
);
CREATE INDEX corporate_event_date_idx ON corporate_event (event_date);

-- migrate:down
DROP TABLE corporate_event;
