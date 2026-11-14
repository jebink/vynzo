# candle-worker

**Phase 2**: not built yet.

OHLCV aggregation (trades -> 1m -> intraday -> daily) and candle corrections. Kept separate from analytics so a candle correction never requires a grading change.

Planned layout: `src/{consumers,aggregators,corrections,calendars,validation,storage}/`, `tests/`.
