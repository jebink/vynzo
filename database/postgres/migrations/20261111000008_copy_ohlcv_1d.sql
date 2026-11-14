-- migrate:up
-- Copy legacy.ohlcv_1d into the listing-keyed public.ohlcv_1d. Values are copied as-is: same
-- column types (double precision / bigint), no casts, no rounding. legacy.* stays intact.
--
-- Guard (same shape in 08-11): raise 'copy mismatch' unless count(*), sum(close) and sum(volume)
-- agree between legacy.X and public.X. A legacy row whose (symbol, exchange) has no listing is
-- dropped by the join and trips the count. sum(close) is taken over close::text::numeric, which
-- is exact (the text form of a float8 is its shortest round-trip decimal when
-- extra_float_digits > 0) and does not depend on row order. A float8 sum(close) does depend on
-- row order, and legacy (7-day chunks) and new (365-day chunks) scan in different orders.

INSERT INTO public.ohlcv_1d (ts, listing_id, open, high, low, close, volume)
SELECT l.ts, li.listing_id, l.open, l.high, l.low, l.close, l.volume
FROM legacy.ohlcv_1d l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

DO $$
DECLARE
    t text;
    old_n bigint; new_n bigint;
    old_close numeric; new_close numeric;
    old_vol numeric; new_vol numeric;
BEGIN
    PERFORM set_config('extra_float_digits', '1', true);
    FOREACH t IN ARRAY ARRAY['ohlcv_1d'] LOOP
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
TRUNCATE public.ohlcv_1d;
