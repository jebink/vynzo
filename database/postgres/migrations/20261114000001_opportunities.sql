-- migrate:up
-- Market opportunities (docs/superpowers/plans/2026-11-14-market-opportunities.md).
-- `opportunity` holds each day's ranked BUY/SELL picks per horizon, with the inputs and
-- calc_version that produced them (architecture rule 5). `opportunity_outcome` records how a
-- pick closed; a pick without an outcome row is still open.

CREATE TABLE opportunity (
    id              BIGSERIAL PRIMARY KEY,
    listing_id      BIGINT           NOT NULL REFERENCES listings (listing_id),
    horizon         TEXT             NOT NULL
                    CHECK (horizon IN ('next_session', 'swing', 'long_term')),
    as_of           TIMESTAMPTZ      NOT NULL,
    direction       TEXT             NOT NULL CHECK (direction IN ('BUY', 'SELL')),
    status          TEXT             NOT NULL CHECK (status IN ('actionable', 'watch')),
    score           SMALLINT         NOT NULL CHECK (score BETWEEN 0 AND 100),
    confidence      TEXT             NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    price           DOUBLE PRECISION NOT NULL,
    entry_low       DOUBLE PRECISION NOT NULL,
    entry_high      DOUBLE PRECISION NOT NULL,
    stop_loss       DOUBLE PRECISION NOT NULL,
    targets         DOUBLE PRECISION[] NOT NULL,
    risk_reward     DOUBLE PRECISION NOT NULL,
    holding_period  TEXT             NOT NULL,
    max_sessions    SMALLINT         NOT NULL,
    supports        DOUBLE PRECISION[] NOT NULL DEFAULT '{}',
    resistances     DOUBLE PRECISION[] NOT NULL DEFAULT '{}',
    reasons         JSONB            NOT NULL,
    factors         JSONB            NOT NULL,
    risks           JSONB            NOT NULL,
    invalidation    JSONB            NOT NULL,
    regime          JSONB            NOT NULL,
    inputs          JSONB            NOT NULL,
    calc_version    TEXT             NOT NULL,
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),
    UNIQUE (listing_id, horizon, as_of)
);

CREATE INDEX idx_opportunity_horizon_as_of ON opportunity (horizon, as_of DESC, score DESC);

COMMENT ON TABLE opportunity IS
  'Daily ranked BUY/SELL picks per horizon from analytics-worker opportunities job.';
COMMENT ON COLUMN opportunity.as_of IS 'Trading date of the daily bar the pick was computed from.';
COMMENT ON COLUMN opportunity.max_sessions IS
  'Sessions after as_of the pick stays open before it expires.';
COMMENT ON COLUMN opportunity.inputs IS 'Feature values the score was computed from.';

CREATE TABLE opportunity_outcome (
    opportunity_id  BIGINT           PRIMARY KEY REFERENCES opportunity (id) ON DELETE CASCADE,
    status          TEXT             NOT NULL
                    CHECK (status IN ('target_hit', 'stopped', 'expired', 'not_triggered')),
    entry_at        TIMESTAMPTZ,
    entry_price     DOUBLE PRECISION,
    exit_at         TIMESTAMPTZ,
    exit_price      DOUBLE PRECISION,
    return_pct      DOUBLE PRECISION,
    sessions_held   SMALLINT,
    calc_version    TEXT             NOT NULL,
    evaluated_at    TIMESTAMPTZ      NOT NULL DEFAULT now()
);

COMMENT ON COLUMN opportunity_outcome.return_pct IS
  'Direction-adjusted return from entry to exit, in percent (positive = the pick was right).';

-- Market-regime inputs: BANK NIFTY and India VIX (NIFTY already exists as ^NSEI). Active, so the
-- next EOD run backfills their full history.
INSERT INTO listings (exchange, symbol, kind, is_active)
VALUES ('NSE', 'BANKNIFTY', 'index', true), ('NSE', 'INDIAVIX', 'index', true)
ON CONFLICT (exchange, symbol) DO NOTHING;

INSERT INTO provider_symbols (provider, provider_symbol, listing_id)
SELECT 'yahoo', v.provider_symbol, l.listing_id
FROM (VALUES ('BANKNIFTY', '^NSEBANK'), ('INDIAVIX', '^INDIAVIX')) AS v (symbol, provider_symbol)
JOIN listings l ON l.exchange = 'NSE' AND l.symbol = v.symbol
ON CONFLICT DO NOTHING;

-- migrate:down
DELETE FROM provider_symbols
WHERE provider = 'yahoo' AND provider_symbol IN ('^NSEBANK', '^INDIAVIX');
-- Keeps the listings if bars were already ingested for them (their FKs would block the delete).
DELETE FROM listings l
WHERE l.exchange = 'NSE' AND l.symbol IN ('BANKNIFTY', 'INDIAVIX')
  AND NOT EXISTS (SELECT 1 FROM ohlcv_1d b WHERE b.listing_id = l.listing_id)
  AND NOT EXISTS (SELECT 1 FROM ingest_runs r WHERE r.listing_id = l.listing_id);
DROP TABLE IF EXISTS opportunity_outcome;
DROP TABLE IF EXISTS opportunity;
