"""One stock on demand, for the API's stock page. Read-only.

- `current`: today's scan per horizon (the same `scan` the daily job runs), with the gate a
  horizon failed when it made no pick.
- `backtest_events`: a walk-forward backtest of every strategy over the stock's whole history,
  using `backtest_listing` and `dedupe` exactly as the system-wide backtest does. It yields
  progress events chunk by chunk so a client can animate the run as it happens.

Strategies are identified as "<horizon>:<key>": "swing:breakout" etc. for the named swing setups
(traded on their own with `setup_plan`), and "<horizon>:factor_confluence" for the engine's picks
in that horizon (for swing, only picks with no named setup, matching the Market screen's filter).
"""

import statistics
from collections.abc import Iterator
from dataclasses import asdict, dataclass

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from analytics_worker.db import load_daily_bars
from analytics_worker.opportunities.backtest import (
    TRIGGERED,
    WINDOW,
    BacktestPick,
    SetupTrade,
    _excess,
    _stats,
    backtest_listing,
    dedupe,
)
from analytics_worker.opportunities.diagnosis import features, loss_reasons
from analytics_worker.opportunities.engine import RECIPES, scan
from analytics_worker.opportunities.job import _index_bars, _latest_session, _until
from analytics_worker.opportunities.regime import Regime, market_regime

FACTOR_CONFLUENCE = "factor_confluence"
CHUNK = 250  # sessions per progress event


@dataclass(frozen=True)
class StockInputs:
    listing_id: int
    symbol: str
    bars: pd.DataFrame
    indexes: dict[str, pd.DataFrame | None]  # NIFTY, BANKNIFTY, INDIAVIX up to the session

    @property
    def benchmark(self) -> pd.Series | None:
        nifty = self.indexes.get("NIFTY")
        return None if nifty is None else nifty["close"]


def load_inputs(conn: psycopg.Connection, listing_id: int, symbol: str) -> StockInputs:
    """Everything `current` and `backtest_events` need, so they never touch the database."""
    cur = conn.cursor(row_factory=dict_row)  # the job's helpers read rows by column name
    session = _latest_session(cur, None)
    bars = load_daily_bars(cur, listing_id)
    if session is not None:
        bars = _until(bars, session)
    indexes = {s: _index_bars(cur, s, session) for s in ("NIFTY", "BANKNIFTY", "INDIAVIX")}
    return StockInputs(listing_id, symbol, bars, indexes)


def _regime_at(inputs: StockInputs, ts: pd.Timestamp) -> Regime:
    def upto(name: str) -> pd.DataFrame | None:
        bars = inputs.indexes.get(name)
        return None if bars is None else bars[bars.index <= ts].iloc[-WINDOW:]

    return market_regime(upto("NIFTY"), upto("BANKNIFTY"), upto("INDIAVIX"))


def current(inputs: StockInputs) -> dict | None:
    """Per horizon: the pick (as the daily job would make it) or why there is none."""
    if inputs.bars.empty:
        return None
    session = inputs.bars.index[-1]
    regime = _regime_at(inputs, session)
    result = scan(inputs.bars, inputs.benchmark, regime)
    horizons: dict[str, dict] = {}
    for horizon in RECIPES:
        pick = next((p for p in (result.picks if result else []) if p.horizon == horizon), None)
        rejection = result.rejections.get(horizon) if result else None
        horizons[horizon] = {
            "pick": asdict(pick) if pick else None,
            "rejection": asdict(rejection) if rejection else None,
        }
        if result is None:
            horizons[horizon]["rejection"] = {"reason": "Not enough history", "factors": []}
    return {
        "as_of": session,
        "regime": asdict(regime),
        "horizons": horizons,
        "setups": [asdict(s) for s in result.setups] if result else [],
    }


def _strategy_items(
    picks: list[BacktestPick], trades: list[SetupTrade]
) -> dict[str, list[BacktestPick | SetupTrade]]:
    """Deduped trades per strategy id. `dedupe` keeps a prefix stable as sessions are added."""
    out: dict[str, list] = {}
    for horizon in RECIPES:
        mine = [p for p in picks if p.horizon == horizon and (horizon != "swing" or not p.setups)]
        out[f"{horizon}:{FACTOR_CONFLUENCE}"] = dedupe(mine)
    for key in sorted({t.key for t in trades}):
        out[f"swing:{key}"] = dedupe([t for t in trades if t.key == key])
    return out


def _trade_json(strategy: str, item, benchmark: pd.Series | None, ctx=None) -> dict:
    """`ctx`: (bars, diagnosis features) to explain a loss; None skips that."""
    o = item.outcome
    return {
        "strategy": strategy,
        "as_of": item.as_of,
        "direction": item.direction,
        "outcome": o.status if o else "open",
        "entry_at": o.entry_at if o else None,
        "entry_price": o.entry_price if o else None,
        "exit_at": o.exit_at if o else None,
        "exit_price": o.exit_price if o else None,
        "return_pct": o.return_pct if o else None,
        "sessions_held": o.sessions_held if o else None,
        "excess_vs_nifty_pct": _excess(item, benchmark) if benchmark is not None else None,
        "loss_reasons": [asdict(r) for r in loss_reasons(item, *ctx, benchmark)] if ctx else [],
    }


def equity_curve(items: list) -> tuple[list[dict], float | None]:
    """Growth of 1 compounding each entered trade's return in exit order, and the max drawdown
    in %. shortcut: trades that overlap are compounded one after another, not as a portfolio."""
    entered = sorted(
        (i for i in items if i.outcome and i.outcome.status in TRIGGERED and i.outcome.exit_at),
        key=lambda i: i.outcome.exit_at,
    )
    equity, peak, drawdown, curve = 1.0, 1.0, 0.0, []
    for i in entered:
        equity *= 1 + (i.outcome.return_pct or 0.0) / 100
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        curve.append({"t": i.outcome.exit_at, "equity": equity})
    return curve, (drawdown * 100 if entered else None)


def summary(items: list, benchmark: pd.Series | None) -> dict:
    curve, max_dd = equity_curve(items)
    held = [i.outcome.sessions_held for i in items if i.outcome and i.outcome.sessions_held]
    return {
        **_stats(items, benchmark),
        "total_return_pct": (curve[-1]["equity"] - 1) * 100 if curve else None,
        "max_drawdown_pct": max_dd,
        "avg_sessions_held": statistics.fmean(held) if held else None,
        "equity": curve,
    }


def backtest_events(inputs: StockInputs, chunk: int = CHUNK) -> Iterator[dict]:
    """start, one progress event per `chunk` sessions (with the trades it closed), then done."""
    bars, benchmark = inputs.bars, inputs.benchmark
    ctx = (bars, features(bars)) if not bars.empty else None
    sessions = list(bars.index)
    yield {
        "type": "start",
        "sessions": len(sessions),
        "first": sessions[0] if sessions else None,
        "last": sessions[-1] if sessions else None,
    }
    picks: list[BacktestPick] = []
    trades: list[SetupTrade] = []
    emitted: dict[str, int] = {}
    for start in range(0, len(sessions), chunk):
        part = sessions[start : start + chunk]
        regimes = {ts: _regime_at(inputs, ts) for ts in part}
        result = backtest_listing(inputs.listing_id, inputs.symbol, bars, benchmark, regimes, part)
        picks += result.picks
        trades += result.setup_trades
        new = []
        for strategy, items in _strategy_items(picks, trades).items():
            new += [
                _trade_json(strategy, i, benchmark, ctx) for i in items[emitted.get(strategy, 0) :]
            ]
            emitted[strategy] = len(items)
        yield {"type": "progress", "done": start + len(part), "through": part[-1], "trades": new}
    yield {
        "type": "done",
        "summary": {s: summary(i, benchmark) for s, i in _strategy_items(picks, trades).items()},
    }
