-- migrate:up
-- Copy legacy.ohlcv_1w and legacy.ohlcv_1mo into the listing-keyed public tables. Values are
-- copied as-is (no casts). legacy.* stays intact. Guard as in 20261111000008.

INSERT INTO public.ohlcv_1w (ts, listing_id, open, high, low, close, volume)
SELECT l.ts, li.listing_id, l.open, l.high, l.low, l.close, l.volume
FROM legacy.ohlcv_1w l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

INSERT INTO public.ohlcv_1mo (ts, listing_id, open, high, low, close, volume)
SELECT l.ts, li.listing_id, l.open, l.high, l.low, l.close, l.volume
FROM legacy.ohlcv_1mo l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

DO $$
DECLARE
    t text;
    old_n bigint; new_n bigint;
    old_close numeric; new_close numeric;
    old_vol numeric; new_vol numeric;
BEGIN
    PERFORM set_config('extra_float_digits', '1', true);
    FOREACH t IN ARRAY ARRAY['ohlcv_1w', 'ohlcv_1mo'] LOOP
        EXECUTE format('SELECT count(*), sum(close::text::numeric), sum(volume) FROM legacy.%I', t)
            INTO old_n, old_close, old_vol;
        EXECUTE format('SELECT count(*), sum(close::text::numeric), sum(volume) FROM public.%I', t)
            INTO new_n, new_close, new_vol;
        IF old_n IS DISTINCT FROM new_n
           OR old_close IS DISTINCT FROM new_close
           OR old_vol IS DISTINCT FROM new_vol THEN
            RAISE EXCEPTION 'copy mismatch: % legacy (rows %, close %, volume %) new (rows %, close %, volume %)',
                t, old_n, old_close, old_vol, new_n, new_close, new_vol;
        END IF;
    END LOOP;
END $$;

-- migrate:down
TRUNCATE public.ohlcv_1w, public.ohlcv_1mo;
