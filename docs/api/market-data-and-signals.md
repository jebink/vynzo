# Market data and signals API (v1)

This is the read-only contract between `services/api` and `apps/web` for price charts and signals.
All routes are under `/v1`. Responses are JSON. Timestamps are ISO-8601 UTC strings.
Daily/weekly/monthly bars sit at `00:00Z` of the trading date.

A stock is addressed by **exchange + symbol** in URLs (`NSE`/`BSE`, upper-case), and by
`listing_id` in responses. An unknown exchange/symbol returns `404 {"detail": "listing not found"}`.
A bad query value returns 422 (FastAPI default).

## Instruments (module `instruments`)

### `GET /v1/instruments/listings`
Search listings for the stock picker.

| Query | Default | Notes |
|---|---|---|
| `q` | none | Case-insensitive prefix match on symbol, or substring match on company name |
| `exchange` | none | `NSE` or `BSE` |
| `active` | `true` | `true` returns only listings in the daily-ingest universe |
| `limit` | `20` | 1–100 |

```json
[{"listing_id": 12, "exchange": "NSE", "symbol": "RELIANCE", "kind": "equity",
  "company_name": "Reliance Industries Limited", "isin": "INE002A01018", "is_active": true}]
```
Ordering: exact symbol match first, then symbol ascending.

### `GET /v1/instruments/listings/{exchange}/{symbol}`
One listing (same shape as above), plus `latest` (the newest `ohlcv_1d` bar, or `null`) and
`previous_close` (the close of the bar before it, or `null`):
```json
{"listing_id": 12, "exchange": "NSE", "symbol": "RELIANCE", "kind": "equity",
 "company_name": "Reliance Industries Limited", "isin": "INE002A01018", "is_active": true,
 "latest": {"ts": "2026-11-09T00:00:00Z", "open": 1320.0, "high": 1330.5, "low": 1315.2,
            "close": 1324.4, "volume": 19734153},
 "previous_close": 1320.0}
```

## Market data (module `market_data`)

### `GET /v1/market-data/overview`
Every ingested listing (one with a row in `provider_symbols`) with its latest daily close and its
last `points` daily closes, for directory pages and sparklines. Used by the web `/stocks` page.
| Query | Default | Notes |
|---|---|---|
| `exchange` | none | `NSE` or `BSE` (case-insensitive) |
| `points` | `60` | 2–250; daily closes per stock |

```json
{"as_of": "2026-11-13T00:00:00Z", "points": 60,
 "stocks": [{"listing_id": 248, "exchange": "NSE", "symbol": "RELIANCE", "kind": "equity",
             "company_name": "Reliance Industries Limited", "is_active": true,
             "latest_ts": "2026-11-13T00:00:00Z", "close": 1339.7, "previous_close": 1339.7,
             "change_pct": 0.0, "volume": 13800000, "closes": [1324.0, 1339.7]}]}
```
Sorted by `symbol`, then `exchange`. `closes` is ascending by date. Only bars within
`points × 2 + 14` calendar days of the newest bar in `ohlcv_1d` are read, so a listing whose data
stopped before that has empty `closes` and `null` price fields; it is still listed. `as_of` is the
newest `latest_ts`, or `null` when no listing has bars.

### `GET /v1/market-data/{exchange}/{symbol}/bars`
| Query | Default | Notes |
|---|---|---|
| `timeframe` | `1d` | One of `1d`, `1w`, `1mo`, `75m`, `15m`, `5m`, `1m` |
| `limit` | `500` | 1–5000; returns the newest N bars |
| `end` | none | ISO date; only bars with `ts < end + 1 day` |

```json
{"listing_id": 12, "exchange": "NSE", "symbol": "RELIANCE", "timeframe": "1d",
 "bars": [{"ts": "2026-11-06T00:00:00Z", "open": 1313.4, "high": 1322.0, "low": 1310.1,
           "close": 1320.0, "volume": 22768301}]}
```
`bars` is in ascending `ts` order, and may be empty.

### `GET /v1/market-data/{exchange}/{symbol}/indicators`
Daily indicators from `ta_daily`. Takes the same `limit`/`end` as bars; ascending `ts`.
```json
{"listing_id": 12, "exchange": "NSE", "symbol": "RELIANCE",
 "rows": [{"ts": "2026-11-06T00:00:00Z", "calc_version": "ta-1",
           "rsi_14": 61.2, "ema_9": 1310.0, "ema_21": 1300.1, "ema_50": 1290.4, "ema_200": 1250.7,
           "macd": 8.1, "macd_signal": 6.0, "macd_hist": 2.1, "atr_14": 21.3, "vwap": 980.2,
           "adx_14": 24.0, "plus_di_14": 28.0, "minus_di_14": 15.0, "rvol_20": 1.4,
           "donchian_high_20": 1330.0, "donchian_low_20": 1260.0, "donchian_high_55": 1340.0,
           "bb_width": 0.08, "obv": 123456789.0, "ema200_slope_20": 12.5,
           "extension_atr": 1.4, "ret_126": 0.12}]}
```
Any indicator may be `null`.

## Signals (module `signals`, new)

### `GET /v1/signals/types`
```json
[{"signal_type": "HIGH_VOLUME_BUY", "count": 313, "latest_as_of": "2026-11-09T00:00:00Z"},
 {"signal_type": "SENTIMENT", "count": 126, "latest_as_of": "2026-11-10T00:00:00Z"}]
```
Ordered by `signal_type`.

### `GET /v1/signals`
| Query | Default | Notes |
|---|---|---|
| `signal_type` | none | Exact match |
| `exchange` | none | `NSE` or `BSE` |
| `symbol` | none | Exact match; usually given together with `exchange` |
| `since` | none | ISO date; `as_of >= since` |
| `limit` | `100` | 1–500 |

```json
[{"id": 901, "listing_id": 12, "exchange": "NSE", "symbol": "RELIANCE",
  "company_name": "Reliance Industries Limited", "signal_type": "HIGH_VOLUME_BUY",
  "as_of": "2026-11-09T00:00:00Z", "strength": 2.41, "price": 1324.4, "volume": 19734153,
  "avg_volume": 8200000.5, "rationale": "High volume buy: …", "meta": {"lookback": 20},
  "calc_version": "hvb-1"}]
```
Ordering: `as_of` descending, then `strength` descending (nulls last), then `id` descending.

### `GET /v1/signals/swing`
Legacy swing signals (`swing_signals`). Takes `exchange`, `symbol` and `limit` (default 100, 1–500).
```json
[{"id": 7, "listing_id": 12, "exchange": "NSE", "symbol": "RELIANCE",
  "as_of": "2026-11-06T00:00:00Z", "signal": "BUY", "entry": 1320.0, "stop_loss": 1280.0,
  "target_1": 1380.0, "target_2": 1420.0, "risk_reward": 1.5, "rationale": "…",
  "calc_version": "legacy-vinzo-core"}]
```
Ordering: `as_of` descending.
