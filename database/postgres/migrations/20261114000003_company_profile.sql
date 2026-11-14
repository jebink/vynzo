-- migrate:up
-- Company profile from Yahoo Finance (market_ingestion profiles job, weekly). Market cap is not
-- stored: the API computes shares_outstanding x price so it moves with the price.
ALTER TABLE companies
    ADD COLUMN sector TEXT,
    ADD COLUMN industry TEXT,
    ADD COLUMN shares_outstanding BIGINT CHECK (shares_outstanding > 0),
    ADD COLUMN profile_updated_at TIMESTAMPTZ;

-- migrate:down
ALTER TABLE companies
    DROP COLUMN sector,
    DROP COLUMN industry,
    DROP COLUMN shares_outstanding,
    DROP COLUMN profile_updated_at;
