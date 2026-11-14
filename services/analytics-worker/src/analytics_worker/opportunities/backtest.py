"""Walk-forward backtest of the opportunity engine. Read-only: nothing is written to the database.

For every session in [start, end] each listing is scored with `score_listing` on its bars up to
that session only (a trailing window of WINDOW bars), exactly as the daily job would have done,
and each pick is closed with `evaluate_outcome` on the bars after it. Repeats of a still-open pick
are dropped (`dedupe`), matching the API's track record.

Each named swing setup (`strategies.py`) is also traded on its own (`setup_trade`), whether or
not the engine made a pick, so every strategy gets its own record: entry within 0.25 ATR of
the signal close, the strategy's stop, first target at SETUP_TARGET_R x the risk, and the
swing recipe's time limit. Results are compared with NIFTY over each trade's own window.

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
from analytics_worker.opportunities.engine import RECIPES, scan
from analytics_worker.opportunities.outcomes import ENTRY_WINDOW, Outcome, evaluate_outcome
from analytics_worker.opportunities.regime import Regime, market_regime
from analytics_worker.opportunities.strategies import Setup

log = logging.getLogger(__name__)

WINDOW = 750  # bars of history per evaluation; EMA-200 differs from full history by < 1%
BANDS = ((85, 100), (70, 84), (55, 69))
SETUP_TARGET_R = 2.0
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
    setups: tuple[str, ...] = ()  # strategy keys attached to the pick


@dataclass(frozen=True)
class SetupTrade:
    """One named setup traded on its own with the standard plan (see the module docstring)."""

    listing_id: int
    symbol: str
    key: str
    variant: str
    as_of: pd.Timestamp
    direction: str
    regime: str
    outcome: Outcome | None


@dataclass(frozen=True)
class ListingResult:
    picks: list[BacktestPick]
    setup_trades: list[SetupTrade]


@dataclass(frozen=True)
class BacktestRun:
    picks: list[BacktestPick]  # raw, not deduped
    setup_trades: list[SetupTrade]  # raw, not deduped
    drift: dict[str, list[float]]  # do-nothing baseline per horizon
    benchmark: pd.Series  # NIFTY closes, for excess returns


def setup_plan(setup: Setup, close: float, atr: float) -> dict:
    """The standard trade for a setup, in the shape `evaluate_outcome` reads."""
    d = 1 if setup.direction == "BUY" else -1
    risk = abs(close - setup.stop)
    return {
        "horizon": "swing",
        "direction": setup.direction,
        "entry_low": close - 0.25 * atr,
        "entry_high": close + 0.25 * atr,
        "stop_loss": setup.stop,
        "targets": [close + d * SETUP_TARGET_R * risk, close + d * (SETUP_TARGET_R + 1) * risk],
        "max_sessions": RECIPES["swing"].max_sessions,
    }


def backtest_listing(
    listing_id: int,
    symbol: str,
    bars: pd.DataFrame,
    benchmark: pd.Series | None,
    regimes: dict[pd.Timestamp, Regime],
    sessions: Iterable[pd.Timestamp],
) -> ListingResult:
    """Score one listing at each of ``sessions`` it traded on; close each pick and setup."""
    picks: list[BacktestPick] = []
    trades: list[SetupTrade] = []
    position = {ts: i for i, ts in enumerate(bars.index)}
    swing_bars = RECIPES["swing"].max_sessions + ENTRY_WINDOW["swing"]
    for session in sessions:
        i = position.get(session)
        if i is None:
            continue
        history = bars.iloc[max(0, i + 1 - WINDOW) : i + 1]
        regime = regimes.get(session, market_regime(None))
        result = scan(history, benchmark, regime)
        if result is None:
            continue
        future = bars.iloc[i + 1 : i + 1 + swing_bars]
        for setup in result.setups:
            plan = setup_plan(setup, result.features.close, result.features.atr14)
            trades.append(
                SetupTrade(
                    listing_id,
                    symbol,
                    setup.key,
                    setup.variant,
                    session,
                    setup.direction,
                    regime.label,
                    evaluate_outcome(plan, future),
                )
            )
        for opp in result.picks:
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
                    tuple(s.key for s in opp.setups),
                )
            )
    return ListingResult(picks, trades)


def _open_on(pick: BacktestPick | SetupTrade, day: pd.Timestamp) -> bool:
    """Was ``pick`` still an open recommendation on ``day``?"""
    if pick.outcome is None:
        return True
    return pick.outcome.exit_at is not None and pick.outcome.exit_at >= day


def _repeat_key(item: BacktestPick | SetupTrade) -> tuple:
    if isinstance(item, SetupTrade):
        return (item.listing_id, "setup", item.key, item.direction)
    return (item.listing_id, item.horizon, item.direction, item.status)


def dedupe[T: (BacktestPick, SetupTrade)](picks: list[T]) -> list[T]:
    """Drop repeats of an earlier still-open pick (same listing, horizon, direction, status)
    or setup trade (same listing, strategy, direction)."""
    history: dict[tuple, list[T]] = defaultdict(list)
    kept = []
    for pick in sorted(picks, key=lambda p: p.as_of):
        key = _repeat_key(pick)
        if not any(_open_on(earlier, pick.as_of) for earlier in history[key]):
            kept.append(pick)
        history[key].append(pick)
    return kept


def _excess(item: BacktestPick | SetupTrade, benchmark: pd.Series) -> float | None:
    """Direction-adjusted return minus NIFTY's over the same entry-to-exit window, in %."""
    o = item.outcome
    if o is None or o.return_pct is None or o.entry_at is None or o.exit_at is None:
        return None
    start, end = benchmark.asof(o.entry_at), benchmark.asof(o.exit_at)
    if not (start > 0 and end > 0):
        return None
    d = 1 if item.direction == "BUY" else -1
    return o.return_pct - d * (end / start - 1) * 100


def _stats(picks: list, benchmark: pd.Series | None = None) -> dict:
    entered = [p for p in picks if p.outcome is not None and p.outcome.status in TRIGGERED]
    returns = [p.outcome.return_pct for p in entered if p.outcome.return_pct is not None]
    hits = sum(p.outcome.status == "target_hit" for p in entered)
    excess = []
    if benchmark is not None:
        excess = [x for x in (_excess(p, benchmark) for p in entered) if x is not None]
    return {
        "picks": len(picks),
        "open": sum(p.outcome is None for p in picks),
        "entered": len(entered),
        "hit_rate": hits / len(entered) if entered else None,
        "avg_return_pct": statistics.fmean(returns) if returns else None,
        "median_return_pct": statistics.median(returns) if returns else None,
        "win_rate": sum(r > 0 for r in returns) / len(returns) if returns else None,
        "excess_vs_nifty_pct": statistics.fmean(excess) if excess else None,
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


def summarize_setups(
    trades: list[SetupTrade], *, split: pd.Timestamp, benchmark: pd.Series | None = None
) -> list[dict]:
    """Stats per (period, strategy, direction). Expects deduped trades."""
    groups: dict[tuple, list[SetupTrade]] = defaultdict(list)
    for t in trades:
        period = "in_sample" if t.as_of < split else "out_of_sample"
        groups[(period, t.key, t.direction)].append(t)
    return [{"group": g, **_stats(groups[g], benchmark)} for g in sorted(groups)]


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


def _work(item: tuple[int, str, pd.DataFrame]) -> tuple[ListingResult, dict[str, list[float]]]:
    lid, symbol, bars = item
    sessions = _WORKER["sessions"]
    result = backtest_listing(lid, symbol, bars, _WORKER["benchmark"], _WORKER["regimes"], sessions)
    drift = {h: forward_drift(bars, sessions, hold) for h, hold in HOLD_FOR_DRIFT.items()}
    return result, drift


# Typical holding period per horizon for the do-nothing baseline.
HOLD_FOR_DRIFT = {"next_session": 1, "swing": 10, "long_term": 120}


def run_backtest(
    conn: psycopg.Connection, *, start: date, end: date, workers: int = 8
) -> BacktestRun:
    """All picks and setup trades between ``start`` and ``end``, and the baseline drift."""
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
    trades: list[SetupTrade] = []
    drift: dict[str, list[float]] = {h: [] for h in RECIPES}
    with ProcessPoolExecutor(
        workers, initializer=_init_worker, initargs=(nifty["close"], regimes, sessions)
    ) as pool:
        for result, listing_drift in pool.map(_work, items, chunksize=4):
            picks += result.picks
            trades += result.setup_trades
            for h, values in listing_drift.items():
                drift[h] += values
    return BacktestRun(picks, trades, drift, nifty["close"])
