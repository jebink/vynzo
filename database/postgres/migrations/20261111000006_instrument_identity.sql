-- migrate:up
-- Instrument identity (architecture rule 1): companies, exchange listings and provider symbols
-- are three distinct identities. Market data is keyed by listing_id (see 20261111000007).

CREATE TABLE companies (
    company_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL,
    isin        TEXT        UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN companies.isin IS 'Equity share ISIN (INE...).';

CREATE TABLE listings (
    listing_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id  BIGINT REFERENCES companies (company_id),
    exchange    exchange_code NOT NULL,
    symbol      TEXT          NOT NULL,
    kind        TEXT          NOT NULL CHECK (kind IN ('equity', 'index')),
    series      TEXT,
    listed_on   DATE,
    is_active   BOOLEAN       NOT NULL DEFAULT false,
    UNIQUE (exchange, symbol)
);

CREATE INDEX idx_listings_company ON listings (company_id);

COMMENT ON TABLE listings IS
  'One row per (exchange, symbol). company_id is NULL for indices and until sync-reference links it.';
COMMENT ON COLUMN listings.series IS 'Exchange series (EQ, BE ...) from the reference file.';
COMMENT ON COLUMN listings.is_active IS
  'True when the listing is in the daily-ingest universe.';

CREATE TABLE provider_symbols (
    provider        TEXT   NOT NULL,
    provider_symbol TEXT   NOT NULL,
    listing_id      BIGINT NOT NULL REFERENCES listings (listing_id),
    PRIMARY KEY (provider, provider_symbol),
    UNIQUE (provider, listing_id)
);

COMMENT ON TABLE provider_symbols IS
  'Provider token for a listing, e.g. yahoo: RELIANCE.NS, INFY.BO, ^NSEI.';

-- migrate:down
DROP TABLE IF EXISTS provider_symbols;
DROP TABLE IF EXISTS listings;
DROP TABLE IF EXISTS companies;
