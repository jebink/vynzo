-- migrate:up
-- Copy legacy.ta_daily into the listing-keyed public.ta_daily. Indicator values are copied
-- as-is (double precision, no casts; NULLs stay NULL). The old code recorded no version, so
-- every migrated row is labelled calc_version = 'legacy-vinzo-core'. computed_at takes its
-- default (the copy time). legacy.* stays intact.

INSERT INTO public.ta_daily (
    ts, listing_id,
    rsi_14, ema_9, ema_21, ema_50, ema_200, macd, macd_signal, macd_hist, atr_14, vwap,
    adx_14, plus_di_14, minus_di_14, rvol_20, donchian_high_20, donchian_low_20,
    donchian_high_55, bb_width, obv, ema200_slope_20, extension_atr, ret_126,
    calc_version
)
SELECT l.ts, li.listing_id,
       l.rsi_14, l.ema_9, l.ema_21, l.ema_50, l.ema_200, l.macd, l.macd_signal, l.macd_hist,
       l.atr_14, l.vwap,
       l.adx_14, l.plus_di_14, l.minus_di_14, l.rvol_20, l.donchian_high_20, l.donchian_low_20,
       l.donchian_high_55, l.bb_width, l.obv, l.ema200_slope_20, l.extension_atr, l.ret_126,
       'legacy-vinzo-core'
FROM legacy.ta_daily l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

-- Guard: a legacy row dropped by the listing join (or any other row-count difference) raises.
DO $$
DECLARE
    old_n bigint;
    new_n bigint;
BEGIN
    SELECT count(*) INTO old_n FROM legacy.ta_daily;
    SELECT count(*) INTO new_n FROM public.ta_daily;
    IF old_n IS DISTINCT FROM new_n THEN
        RAISE EXCEPTION 'copy mismatch: ta_daily legacy (rows %) new (rows %)', old_n, new_n;
    END IF;
END $$;

-- migrate:down
TRUNCATE public.ta_daily;
