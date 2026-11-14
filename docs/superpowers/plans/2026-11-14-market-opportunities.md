# Market opportunities (Phase 1)

Approved 2026-11-14. Turns the Market screen into ranked BUY/SELL opportunities for three
horizons, built only on data VYNZO has today: daily OHLCV (278 listings, history to 1996) and
NIFTY, plus BANK NIFTY and India VIX added here. Phase 2 (intraday feed, fundamentals and
sector, FII/DII, delivery volume, news) needs new data sources and is out of scope.

## Decisions
- **Intraday** = "Next-session setups": candidates for the next trading session computed from the
  last close. Labelled as not live.
- **Long-term** = technical only (200-EMA trend, 6-12 month relative strength, base breakouts),
  confidence capped at Medium, labelled "Fundamentals not yet included".
- **SELL** on swing/long-term means exit or avoid (cash-market shorts cannot be held overnight in
  India; a short needs F&O). The UI says so.
- **"Not investment advice"** notice on the page. Recommending trades to third parties in India
  generally needs SEBI Research Analyst registration; review before exposing to other users.

## Design
- `analytics-worker/opportunities/` (pure functions, no I/O except `job.py`):
  - `features.py`: indicators at the last bar, computed from bars with `indicators/ta.py`.
  - `levels.py`: support/resistance from swing pivots.
  - `regime.py`: market regime from NIFTY, BANK NIFTY and India VIX, in [-1, 1].
  - `engine.py`: per-horizon recipes (`next_session`, `swing`, `long_term`). Factor groups
    (trend, momentum, price action, volume, volatility, relative strength) each score [-1, 1]
    with a reason. Score 0-100 from the weighted, direction-aligned sum, minus penalties
    (conflicting groups, opposing regime, high volatility, poor risk/reward). Needs >= 3
    agreeing groups (confluence). Liquidity and price floors exclude illiquid and penny stocks.
    `actionable` needs a high score, Medium+ confidence and enough risk/reward; otherwise `watch`;
    below the watch floor nothing is emitted.
  - Trade plan: entry range, ATR/pivot stop, targets from resistance/support and R multiples,
    risk/reward, holding period, invalidation conditions and risks.
  - `job.py`: daily run over active listings whose last bar is the latest session; dedupes a
    company listed on both exchanges (keeps NSE); replaces that day's rows per horizon.
  - `outcomes.py`: closes picks against later bars (target hit, stopped, expired, not triggered);
    a bar that touches both stop and target counts as stopped.
- Migration: `opportunity` (one row per listing, horizon, as_of; inputs and `calc_version` stored,
  rule 5) and `opportunity_outcome` (closed results). BANK NIFTY (`^NSEBANK`) and India VIX
  (`^INDIAVIX`) index listings; the next EOD run backfills their history.
- Cron: `opportunities` and `opportunity-outcomes` jobs after `indicators` in the 17:00 IST chain.
- API module `opportunities`: list by horizon with filters, detail, performance by horizon and
  score band.
- Web `/market`: three sections (tabs) ranked by score, BUY/SELL and confidence filters, detail
  view with reasons and factor breakdown, performance, data timestamp and the empty state
  "No High-Conviction Opportunities Currently Available". Sector filter hidden until sector data
  exists.

## Tests
Engine unit tests on synthetic bars (uptrend breakout -> BUY, downtrend -> SELL, choppy -> none,
confluence floor, long-term confidence cap, trade-plan geometry). Integration tests for the job,
outcomes and the API on throwaway databases.

## Backtest (2026-11-14, engine opp-1.3.0 → opp-1.4.0)
Walk-forward over the dev data, read-only: `python -m analytics_worker backtest --start 2018-01-01
--end 2026-11-13` (`opportunities/backtest.py`). Each session scores each listing on its bars up
to that day only, exactly as the daily job would; outcomes come from later bars; repeats of a
still-open pick are dropped. Rules were chosen on 2018-2022 (in-sample) and checked on
2023-2026 (out-of-sample). 277 listings x 2185 sessions, 57,952 picks after de-duplication.

Average return per entered pick, and the same minus NIFTY over the pick's own entry-to-exit
window (opp-1.3.0):

| Group | Period | Entered | Avg return | vs NIFTY |
|---|---|---|---|---|
| Long-term BUY actionable | 2018-22 / 2023-26 | 423 / 404 | +6.1% / +5.6% | +2.9% / +4.2% |
| Long-term SELL actionable | 2018-22 / 2023-26 | 194 / 164 | -3.5% / -4.1% | +1.8% / -1.4% |
| Swing BUY actionable | 2018-22 / 2023-26 | 1679 / 1719 | +0.5% / +0.8% | -0.3% / +0.4% |
| Swing SELL actionable | 2018-22 / 2023-26 | 922 / 1031 | -0.2% / -1.2% | +0.1% / -0.7% |
| Swing BUY, bearish regime (all) | 2018-22 / 2023-26 | 274 / 343 | — | -1.9% / -0.7% |
| Next-session (watch) | 2018-22 / 2023-26 | 11150 / 12243 | -0.6% / -0.4% | — |

Changes in opp-1.4.0 (each negative in-sample and again out-of-sample):
- SELL picks are always `watch`, with a "Monitor only" risk line.
- No `actionable` BUY when the slow market regime is against it (bearish).

Not changed, and why:
- Swing BUY shows no edge over NIFTY in either period, and its score does not rank outcomes
  (85-100 is not better than 55-69). Keeping or demoting it is a product decision.
- Long-term BUY beats NIFTY in both periods, but medians are near zero and the universe is
  today's 277 selected (surviving) stocks, which flatters long holds most. Treat as unproven.
- Next-session is already watch-only; it loses money on average.

Caveats: survivorship bias (delisted stocks are missing), no costs, slippage or taxes, and
returns are per pick, not a portfolio.
