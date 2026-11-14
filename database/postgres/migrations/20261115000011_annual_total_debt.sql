-- migrate:up
-- Total debt at each fiscal year end (Yahoo balance sheet), for the "debt cleared" indicator.
ALTER TABLE company_annual_financials ADD COLUMN total_debt DOUBLE PRECISION;

-- migrate:down
ALTER TABLE company_annual_financials DROP COLUMN total_debt;
