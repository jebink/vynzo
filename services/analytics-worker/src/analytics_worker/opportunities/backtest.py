"""Walk-forward backtest of the opportunity engine. Read-only: nothing is written to the database.

For every session in [start, end] each listing is scored with `score_listing` on its bars up to
that session only (a trailing window of WINDOW bars), exactly as the daily job would have done,
and each pick is closed with `evaluate_outcome` on the bars after it. Repeats of a still-open pick
are dropped (`dedupe`), matching the API's track record.

Caveats, printed with every report:
- Survivorship: the universe is today's active listings; delisted losers are missing.
- Fills follow the outcome rules (open clamped into the entry range; stop wins a bar that touches
  both); no costs, slippage or taxes.
"""

import logging
import statistics
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd
import psycopg

from analytics_worker.db import load_daily_bars
from analytics_worker.opportunities.engine import RECIPES, score_listing
from analytics_worker.opportunities.outcomes import ENTRY_WINDOW, Outcome, evaluate_outcome
from analytics_worker.opportunities.regime import Regime, market_regime

log = logging.getLogger(__name__)

WINDOW = 750  # bars of history per evaluation; EMA-200 differs from full history by < 1%
BANDS = ((85, 100), (70, 84), (55, 69))
TRIGGERED = ("target_hit", "stopped", "expired")


@dataclass(frozen=True)
class BacktestPick:
    listing_id: int
    symbol: str
    horizon: str
    as_of: pd.Timestamp
    direction: str
    status: str
    score: int
    confidence: str
    regime: str
    outcome: Outcome | None  # None: still open when the data ends


def backtest_listing(
    listing_id: int,
    symbol: str,
    bars: pd.DataFrame,
    benchmark: pd.Series | None,
    regimes: dict[pd.Timestamp, Regime],
    sessions: Iterable[pd.Timestamp],
) -> list[BacktestPick]:
    """Score one listing at each of ``sessions`` it traded on and close each pick."""
    picks: list[BacktestPick] = []
    position = {ts: i for i, ts in enumerate(bars.index)}
    for session in sessions:
        i = position.get(session)
        if i is None:
            continue
        history = bars.iloc[max(0, i + 1 - WINDOW) : i + 1]
        regime = regimes.get(session, market_regime(None))
        for opp in score_listing(history, benchmark, regime) or []:
            horizon_bars = opp.max_sessions + ENTRY_WINDOW[opp.horizon]
            future = bars.iloc[i + 1 : i + 1 + horizon_bars]
            outcome = evaluate_outcome(asdict(opp), future)
            picks.append(
                BacktestPick(
                    listing_id,
                    symbol,
                    opp.horizon,
                    session,
                    opp.direction,
                    opp.status,
                    opp.score,
                    opp.confidence,
                    regime.label,
                    outcome,
                )
            )
    return picks


def _open_on(pick: BacktestPick, day: pd.Timestamp) -> bool:
    """Was ``pick`` still an open recommendation on ``day``?"""
    if pick.outcome is None:
        return True
    return pick.outcome.exit_at is not None and pick.outcome.exit_at >= day


def dedupe(picks: list[BacktestPick]) -> list[BacktestPick]:
    """Drop repeats of an earlier still-open pick (same listing, horizon, direction, status)."""
    history: dict[tuple, list[BacktestPick]] = defaultdict(list)
    kept = []
    for pick in sorted(picks, key=lambda p: p.as_of):
        key = (pick.listing_id, pick.horizon, pick.direction, pick.status)
        if not any(_open_on(earlier, pick.as_of) for earlier in history[key]):
            kept.append(pick)
        history[key].append(pick)
    return kept


def _stats(picks: list[BacktestPick]) -> dict:
    entered = [p for p in picks if p.outcome is not None and p.outcome.status in TRIGGERED]
    returns = [p.outcome.return_pct for p in entered if p.outcome.return_pct is not None]
    hits = sum(p.outcome.status == "target_hit" for p in entered)
    return {
        "picks": len(picks),
        "open": sum(p.outcome is None for p in picks),
        "entered": len(entered),
        "hit_rate": hits / len(entered) if entered else None,
        "avg_return_pct": statistics.fmean(returns) if returns else None,
        "median_return_pct": statistics.median(returns) if returns else None,
        "win_rate": sum(r > 0 for r in returns) / len(returns) if returns else None,
    }


def summarize(picks: list[BacktestPick], *, split: pd.Timestamp) -> list[dict]:
    """Stats per (period, horizon, direction, status), with score bands. Expects deduped picks."""
    groups: dict[tuple, list[BacktestPick]] = defaultdict(list)
    for p in picks:
        period = "in_sample" if p.as_of < split else "out_of_sample"
        groups[(period, p.horizon, p.direction, p.status)].append(p)
    rows = []
    for group in sorted(groups):
        members = groups[group]
        bands = {
            f"{lo}-{hi}": _stats([p for p in members if lo <= p.score <= hi]) for lo, hi in BANDS
        }
        rows.append({"group": group, **_stats(members), "bands": bands})
    return rows


def forward_drift(bars: pd.DataFrame, sessions: list[pd.Timestamp], hold: int) -> list[float]:
    """Close-to-close % return over ``hold`` sessions from each session (do-nothing baseline)."""
    close = bars["close"]
    position = {ts: i for i, ts in enumerate(bars.index)}
    out = []
    for s in sessions:
        i = position.get(s)
        if i is not None and i + hold < len(close):
            out.append((float(close.iloc[i + hold]) / float(close.iloc[i]) - 1) * 100)
    return out


# ---- Runner (read-only I/O) ----

_WORKER: dict = {}


def _init_worker(benchmark, regimes, sessions):
    _WORKER.update(benchmark=benchmark, regimes=regimes, sessions=sessions)


def _work(item: tuple[int, str, pd.DataFrame]) -> tuple[list[BacktestPick], dict[str, list[float]]]:
    lid, symbol, bars = item
    sessions = _WORKER["sessions"]
    picks = backtest_listing(lid, symbol, bars, _WORKER["benchmark"], _WORKER["regimes"], sessions)
    drift = {h: forward_drift(bars, sessions, hold) for h, hold in HOLD_FOR_DRIFT.items()}
    return picks, drift


# Typical holding period per horizon for the do-nothing baseline.
HOLD_FOR_DRIFT = {"next_session": 1, "swing": 10, "long_term": 120}


def run_backtest(
    conn: psycopg.Connection, *, start: date, end: date, workers: int = 8
) -> tuple[list[BacktestPick], dict[str, list[float]]]:
    """All picks between ``start`` and ``end`` (raw, not deduped) and the baseline drift."""
    conn.read_only = True
    rows = conn.execute(
        "SELECT l.listing_id, l.symbol FROM listings l WHERE l.is_active AND l.kind = 'equity' "
        "AND EXISTS (SELECT 1 FROM ohlcv_1d b WHERE b.listing_id = l.listing_id) "
        "ORDER BY (l.exchange = 'NSE') DESC, l.listing_id"
    ).fetchall()
    index_ids = {
        r["symbol"]: r["listing_id"]
        for r in conn.execute(
            "SELECT symbol, listing_id FROM listings WHERE exchange = 'NSE' "
            "AND symbol IN ('NIFTY', 'BANKNIFTY', 'INDIAVIX')"
        ).fetchall()
    }
    indexes = {s: load_daily_bars(conn, lid) for s, lid in index_ids.items()}
    nifty = indexes.get("NIFTY")
    if nifty is None or nifty.empty:
        raise RuntimeError("NIFTY bars are required for the backtest")
    lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    sessions = [ts for ts in nifty.index if lo <= ts <= hi]

    def upto(name: str, ts: pd.Timestamp) -> pd.DataFrame | None:
        bars = indexes.get(name)
        if bars is None or bars.empty:
            return None
        return bars[bars.index <= ts].iloc[-WINDOW:]

    regimes = {
        ts: market_regime(upto("NIFTY", ts), upto("BANKNIFTY", ts), upto("INDIAVIX", ts))
        for ts in sessions
    }
    items = [(r["listing_id"], r["symbol"], load_daily_bars(conn, r["listing_id"])) for r in rows]
    conn.rollback()
    log.info("backtest: %d listings x %d sessions", len(items), len(sessions))

    picks: list[BacktestPick] = []
    drift: dict[str, list[float]] = {h: [] for h in RECIPES}
    with ProcessPoolExecutor(
        workers, initializer=_init_worker, initargs=(nifty["close"], regimes, sessions)
    ) as pool:
        for listing_picks, listing_drift in pool.map(_work, items, chunksize=4):
            picks += listing_picks
            for h, values in listing_drift.items():
                drift[h] += values
    return picks, drift
