-- migrate:up
-- Company fundamentals from Yahoo Finance (fundamentals_worker fundamentals job, daily) and major
-- orders pulled from news headlines (analytics_worker orders job). Amounts are in INR; every
-- metric is nullable because Yahoo often lacks values for smaller NSE companies.

-- Ratio snapshot, one per company per day (a re-run the same day replaces it).
CREATE TABLE company_fundamentals (
    company_id              BIGINT      NOT NULL REFERENCES companies (company_id) ON DELETE CASCADE,
    as_of                   DATE        NOT NULL,
    trailing_pe             DOUBLE PRECISION,
    forward_pe              DOUBLE PRECISION,
    price_to_book           DOUBLE PRECISION,
    revenue_ttm             DOUBLE PRECISION,
    revenue_growth          DOUBLE PRECISION,  -- year on year, fraction (0.26 = +26%)
    net_income_ttm          DOUBLE PRECISION,
    profit_margin           DOUBLE PRECISION,  -- fraction
    return_on_equity        DOUBLE PRECISION,  -- fraction
    total_debt              DOUBLE PRECISION,
    total_cash              DOUBLE PRECISION,
    debt_to_equity          DOUBLE PRECISION,  -- ratio (0.32 = 32% of equity)
    current_ratio           DOUBLE PRECISION,
    free_cash_flow          DOUBLE PRECISION,
    insider_pct             DOUBLE PRECISION,  -- promoters and insiders, fraction
    institutional_pct       DOUBLE PRECISION,  -- fraction
    source                  TEXT        NOT NULL DEFAULT 'yahoo',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, as_of)
);

-- Annual income-statement figures for the revenue / profit trend.
CREATE TABLE company_annual_financials (
    company_id      BIGINT  NOT NULL REFERENCES companies (company_id) ON DELETE CASCADE,
    fiscal_year_end DATE    NOT NULL,
    revenue         DOUBLE PRECISION,
    net_income      DOUBLE PRECISION,
    PRIMARY KEY (company_id, fiscal_year_end)
);

-- Dividend history per share (ex-date), for the trailing-12-month total and payout list.
CREATE TABLE company_dividend (
    company_id  BIGINT           NOT NULL REFERENCES companies (company_id) ON DELETE CASCADE,
    ex_date     DATE             NOT NULL,
    amount      DOUBLE PRECISION NOT NULL CHECK (amount > 0),
    PRIMARY KEY (company_id, ex_date)
);

-- Orders, contracts and major projects reported in news headlines (may be incomplete).
CREATE TABLE company_order (
    id            BIGSERIAL   PRIMARY KEY,
    company_id    BIGINT      NOT NULL REFERENCES companies (company_id) ON DELETE CASCADE,
    reported_on   DATE        NOT NULL,
    counterparty  TEXT,
    description   TEXT        NOT NULL,
    value_inr     DOUBLE PRECISION CHECK (value_inr > 0),
    source_url    TEXT        NOT NULL,
    headline      TEXT        NOT NULL,
    model         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, source_url)
);
CREATE INDEX company_order_recent_idx ON company_order (company_id, reported_on DESC);

-- migrate:down
DROP TABLE company_order;
DROP TABLE company_dividend;
DROP TABLE company_annual_financials;
DROP TABLE company_fundamentals;
