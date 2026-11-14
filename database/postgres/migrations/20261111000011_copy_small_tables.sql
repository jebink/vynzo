-- migrate:up
-- Copy the small legacy tables into their listing-keyed public tables: intraday bars
-- (1m/5m/15m/75m), ingest_runs, ohlcv_gaps, signal and swing_signals. Values are copied as-is
-- (no casts). Original ids are kept, then each id sequence is moved past the max id.
-- legacy.* stays intact.

-- legacy.ohlcv_daily is neither copied nor a listing source (20261111000007), so it must be
-- empty: rows there would be lost silently at the legacy drop.
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT count(*) INTO n FROM legacy.ohlcv_daily;
    IF n > 0 THEN
        RAISE EXCEPTION 'legacy.ohlcv_daily not empty: % rows', n;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Intraday bars
-- ---------------------------------------------------------------------------
INSERT INTO public.ohlcv_1m (ts, listing_id, open, high, low, close, volume)
SELECT l.ts, li.listing_id, l.open, l.high, l.low, l.close, l.volume
FROM legacy.ohlcv_1m l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

INSERT INTO public.ohlcv_5m (ts, listing_id, open, high, low, close, volume)
SELECT l.ts, li.listing_id, l.open, l.high, l.low, l.close, l.volume
FROM legacy.ohlcv_5m l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

INSERT INTO public.ohlcv_15m (ts, listing_id, open, high, low, close, volume)
SELECT l.ts, li.listing_id, l.open, l.high, l.low, l.close, l.volume
FROM legacy.ohlcv_15m l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

INSERT INTO public.ohlcv_75m (ts, listing_id, open, high, low, close, volume)
SELECT l.ts, li.listing_id, l.open, l.high, l.low, l.close, l.volume
FROM legacy.ohlcv_75m l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

-- ---------------------------------------------------------------------------
-- Ingestion audit (vinzo-core only ever used Yahoo)
-- ---------------------------------------------------------------------------
INSERT INTO public.ingest_runs (
    id, started_at, finished_at, listing_id, provider, timeframe, rows_upserted, gaps_found,
    status, notes
)
SELECT l.id, l.started_at, l.finished_at, li.listing_id, 'yahoo', l.timeframe, l.rows_upserted,
       l.gaps_found, l.status, l.notes
FROM legacy.ingest_runs l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

INSERT INTO public.ohlcv_gaps (
    id, detected_at, listing_id, timeframe, gap_start, gap_end, resolved
)
SELECT l.id, l.detected_at, li.listing_id, l.timeframe, l.gap_start, l.gap_end, l.resolved
FROM legacy.ohlcv_gaps l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

-- ---------------------------------------------------------------------------
-- Signals (the old code recorded no version)
-- ---------------------------------------------------------------------------
INSERT INTO public.signal (
    id, created_at, as_of, listing_id, signal_type, strength, price, volume, avg_volume,
    rationale, meta, calc_version
)
SELECT l.id, l.created_at, l.as_of, li.listing_id, l.signal_type, l.strength, l.price, l.volume,
       l.avg_volume, l.rationale, l.meta, 'legacy-vinzo-core'
FROM legacy.signal l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

INSERT INTO public.swing_signals (
    id, created_at, as_of, listing_id, signal, entry, stop_loss, target_1, target_2,
    risk_reward, rationale, meta, calc_version
)
SELECT l.id, l.created_at, l.as_of, li.listing_id, l.signal, l.entry, l.stop_loss, l.target_1,
       l.target_2, l.risk_reward, l.rationale, l.meta, 'legacy-vinzo-core'
FROM legacy.swing_signals l
JOIN listings li ON li.exchange = l.exchange AND li.symbol = l.symbol;

-- ---------------------------------------------------------------------------
-- Sequences: next id = max(id) + 1, or 1 when the table is empty.
-- ---------------------------------------------------------------------------
SELECT setval(pg_get_serial_sequence('public.ingest_runs', 'id'),
              coalesce(max(id), 1), max(id) IS NOT NULL) FROM public.ingest_runs;
SELECT setval(pg_get_serial_sequence('public.ohlcv_gaps', 'id'),
              coalesce(max(id), 1), max(id) IS NOT NULL) FROM public.ohlcv_gaps;
SELECT setval(pg_get_serial_sequence('public.signal', 'id'),
              coalesce(max(id), 1), max(id) IS NOT NULL) FROM public.signal;
SELECT setval(pg_get_serial_sequence('public.swing_signals', 'id'),
              coalesce(max(id), 1), max(id) IS NOT NULL) FROM public.swing_signals;

-- ---------------------------------------------------------------------------
-- Guards (see 20261111000008): bars compare count, exact sum(close) and sum(volume);
-- the other tables compare count.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t text;
    old_n bigint; new_n bigint;
    old_close numeric; new_close numeric;
    old_vol numeric; new_vol numeric;
BEGIN
    PERFORM set_config('extra_float_digits', '1', true);
    FOREACH t IN ARRAY ARRAY['ohlcv_1m', 'ohlcv_5m', 'ohlcv_15m', 'ohlcv_75m'] LOOP
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
    FOREACH t IN ARRAY ARRAY['ingest_runs', 'ohlcv_gaps', 'signal', 'swing_signals'] LOOP
        EXECUTE format('SELECT count(*) FROM legacy.%I', t) INTO old_n;
        EXECUTE format('SELECT count(*) FROM public.%I', t) INTO new_n;
        IF old_n IS DISTINCT FROM new_n THEN
            RAISE EXCEPTION 'copy mismatch: % legacy (rows %) new (rows %)', t, old_n, new_n;
        END IF;
    END LOOP;
END $$;

-- migrate:down
-- RESTART IDENTITY also resets the id sequences that the up section moved with setval.
TRUNCATE public.ohlcv_1m, public.ohlcv_5m, public.ohlcv_15m, public.ohlcv_75m,
         public.ingest_runs, public.ohlcv_gaps, public.signal, public.swing_signals
    RESTART IDENTITY;
