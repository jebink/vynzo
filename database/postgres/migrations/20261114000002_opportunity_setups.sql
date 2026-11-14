-- migrate:up
-- Named swing strategies (analytics_worker/opportunities/strategies.py) that agree with a pick:
-- [{"key": "breakout", "variant": "", "reason": "Closed above the 20-day high ..."}].
-- Empty for picks made before opp-1.5.0 and for other horizons.
ALTER TABLE opportunity ADD COLUMN setups JSONB NOT NULL DEFAULT '[]'::jsonb;

-- migrate:down
ALTER TABLE opportunity DROP COLUMN setups;
