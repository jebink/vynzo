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

### Ingestion selection (admin UI `/admin`)
Which listings the daily pipeline runs over. Selection is `listings.is_active`, which EOD
ingestion, indicators and the high-volume-buy signal all filter on; ingestion also needs a Yahoo
provider symbol. **No auth yet (Phase 2): anyone who can reach the API can change it.**

#### `GET /v1/instruments/selection`
One row per symbol with its NSE and BSE listing (`null` where none exists).
| Query | Default | Notes |
|---|---|---|
| `q` | none | Symbol prefix or company-name substring (case-insensitive) |
| `status` | `all` | `all`, `selected` (any listing selected) or `unselected` |
| `offset` / `limit` | `0` / `50` | `limit` 1–200; rows ordered by symbol |

```json
{"total": 2646, "selected": {"NSE": 276, "BSE": 2},
 "rows": [{"symbol": "RELIANCE", "company_name": "Reliance Industries Limited",
           "isin": "INE002A01018", "kind": "equity",
           "nse": {"listing_id": 248, "is_active": true, "provider_symbol": "RELIANCE.NS",
                   "last_bar": "2026-11-13T00:00:00Z"},
           "bse": null}]}
```
`last_bar` is the newest `ohlcv_1d` ts, looked up only for listings with a provider symbol.

#### `PUT /v1/instruments/selection/{exchange}/{symbol}`
Body `{"selected": true|false}`; returns the updated row (shape as above).
- Selecting adds the Yahoo provider symbol if missing (`SYMBOL.NS` / `SYMBOL.BO`). With no
  checkpoint, the next daily run fetches the listing's full history.
- Selecting BSE for a symbol only listed on NSE creates the BSE listing for the same company.
  BSE assumes the NSE symbol; a company with a different BSE symbol fails at fetch time.
- Deselecting keeps all data; deselecting a listing that does not exist is a no-op.
- `404` unknown symbol; `409` no company to create a listing for (index or unlinked listing);
  `422` bad exchange or body.

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

## Opportunities (module `opportunities`)
Ranked BUY/SELL picks per horizon (`next_session`, `swing`, `long_term`) from analytics-worker's
`opportunities` job (end-of-day data; design in
`docs/superpowers/plans/2026-11-14-market-opportunities.md`). Read-only. Not investment advice.

### `GET /v1/opportunities`
The newest session's picks, grouped by horizon; each list is actionable first, then by score.
```json
{"as_of": "2026-11-13T00:00:00Z", "generated_at": "2026-11-13T11:52:10Z",
 "regime": {"score": 0.5, "label": "bullish", "short_term": 1.0, "notes": ["NIFTY above its 20-day EMA, +9.6% over 10 sessions"]},
 "data_note": "Computed from end-of-day prices (Yahoo Finance) after the close; not real-time. Not investment advice.",
 "horizons": {"next_session": [], "long_term": [],
   "swing": [{"id": 812, "listing_id": 12, "exchange": "NSE", "symbol": "MCX", "company_name": "Multi Commodity Exchange of India Limited",
              "horizon": "swing", "as_of": "2026-11-13T00:00:00Z", "direction": "BUY", "status": "actionable",
              "score": 100, "confidence": "high", "price": 3720.0, "entry_low": 3688.97, "entry_high": 3732.41,
              "stop_loss": 3400.38, "targets": [4331.32, 4641.63], "risk_reward": 2.0,
              "holding_period": "5–20 trading sessions", "supports": [3512.4], "resistances": [],
              "reasons": ["Breakout above the 20-day high 3645.00"],
              "factors": [{"group": "trend", "score": 1.0, "reason": "Close above the 21-day EMA, ..."}],
              "risks": ["No earnings or events calendar yet: ..."], "invalidation": ["Daily close below the stop-loss 3400.38"],
              "setups": [{"key": "breakout", "variant": "", "reason": "Closed above the 20-day high 3645.00 on 2.1× normal volume"}],
              "calc_version": "opp-1.5.0"}]}}
```
`status`: `actionable` passed every check; `watch` is monitor-only. Next-session picks are always
`watch` until an intraday feed exists. Since `opp-1.4.0`, SELL picks are always `watch`, and a BUY
is never `actionable` in a bearish market regime (backtest results in the plan doc).

`setups` (swing only, since `opp-1.5.0`; `[]` otherwise) lists the named swing strategies that
agree with the pick. `key` is one of `trend_pullback`, `breakout`, `ma_crossover` (`variant`
`9/21` or `50/200`), `rsi_pullback`, `macd_momentum`, `squeeze_breakout`, `support_bounce`,
`relative_strength`, `volume_accumulation`, `chart_pattern` (`variant` `flag`, `cup_and_handle`,
`double_bottom`, `ascending_triangle`). Setups label a pick; they do not change its score or status. `as_of` is `null` (and every list empty) before the first run.

### `GET /v1/opportunities/{id}`
One pick (same fields) plus `regime`, `inputs` (the feature values it was scored from) and
`outcome` (`null` while open; else `status` target_hit | stopped | expired | not_triggered,
entry/exit prices and dates, `return_pct` direction-adjusted, `sessions_held`). `404` if unknown.

### `GET /v1/opportunities/performance?status=actionable|watch|all`
Track record per horizon (default `actionable`): `picks`, `open`, `closed` counts per outcome,
`hit_rate` (target hits / entered picks), `avg_return_pct` (entered picks), `by_score` bands
(85-100, 70-84, 55-69), and the latest 20 closed picks in `recent`. A pick that repeats an
earlier, still-open pick (same listing, horizon and direction) is not counted again.
