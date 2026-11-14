"""Business use cases for opportunities. Calls the repository; knows nothing about HTTP.

Picks are produced by analytics-worker (opportunities job) from end-of-day bars; this module
only reads and summarises them.
"""

import json
import math
import threading
from collections import OrderedDict
from collections.abc import Iterator
from typing import Any

import pandas as pd
import psycopg
from analytics_worker.opportunities import stock

from app.modules.companies import market_cap
from app.modules.instruments.service import require_listing
from app.modules.opportunities import repository

HORIZONS = ("next_session", "swing", "long_term")
OUTCOME_STATUSES = ("target_hit", "stopped", "expired", "not_triggered")
SCORE_BANDS = ((85, 100), (70, 84), (55, 69))
DATA_NOTE = (
    "Computed from end-of-day prices (Yahoo Finance) after the close; not real-time. "
    "Not investment advice."
)
RECENT_LIMIT = 20


class PickNotFound(Exception):
    """No opportunity with this id."""


def current(conn: psycopg.Connection) -> dict[str, Any]:
    session = repository.latest_session(conn)
    horizons: dict[str, list] = {h: [] for h in HORIZONS}
    if session is None:
        return {
            "as_of": None,
            "generated_at": None,
            "regime": None,
            "data_note": DATA_NOTE,
            "horizons": horizons,
        }
    for row in repository.picks_for(conn, session["as_of"]):
        row.update(market_cap(row.pop("shares_outstanding"), row["price"]))
        horizons[row["horizon"]].append(row)
    return {
        "as_of": session["as_of"],
        "generated_at": session["generated_at"],
        "regime": session["regime"],
        "data_note": DATA_NOTE,
        "horizons": horizons,
    }


def detail(conn: psycopg.Connection, pick_id: int) -> dict[str, Any]:
    row = repository.pick(conn, pick_id)
    if row is None:
        raise PickNotFound
    outcome = None
    if row["outcome_status"] is not None:
        outcome = {
            "status": row["outcome_status"],
            **{
                k: row[k]
                for k in (
                    "entry_at",
                    "entry_price",
                    "exit_at",
                    "exit_price",
                    "return_pct",
                    "sessions_held",
                )
            },
        }
    return {**row, "outcome": outcome}


def _stats(rows: list[dict[str, Any]]) -> tuple[int, float | None, float | None]:
    """(triggered, hit rate, average return) over closed picks that were entered."""
    triggered = [r for r in rows if r["status"] in ("target_hit", "stopped", "expired")]
    if not triggered:
        return 0, None, None
    hits = sum(r["status"] == "target_hit" for r in triggered)
    returns = [r["return_pct"] for r in triggered if r["return_pct"] is not None]
    return len(triggered), hits / len(triggered), (sum(returns) / len(returns) if returns else None)


PICK_STATUSES = {"actionable": ["actionable"], "watch": ["watch"], "all": ["actionable", "watch"]}


def performance(conn: psycopg.Connection, status: str = "actionable") -> dict[str, Any]:
    """Track record of picks with ``status`` (actionable, watch or all)."""
    statuses = PICK_STATUSES[status]
    results = repository.pick_results(conn, statuses)
    horizons = {}
    for horizon in HORIZONS:
        rows = [r for r in results if r["horizon"] == horizon]
        closed = [r for r in rows if r["status"] is not None]
        _, hit_rate, avg_return = _stats(closed)
        bands = []
        for lo, hi in SCORE_BANDS:
            in_band = [r for r in closed if lo <= r["score"] <= hi]
            triggered, band_hit, band_return = _stats(in_band)
            bands.append(
                {
                    "band": f"{lo}-{hi}",
                    "triggered": triggered,
                    "hit_rate": band_hit,
                    "avg_return_pct": band_return,
                }
            )
        horizons[horizon] = {
            "picks": len(rows),
            "open": len(rows) - len(closed),
            "closed": {s: sum(r["status"] == s for r in closed) for s in OUTCOME_STATUSES},
            "hit_rate": hit_rate,
            "avg_return_pct": avg_return,
            "by_score": bands,
        }
    return {
        "status": status,
        "horizons": horizons,
        "recent": repository.recent_closed(conn, statuses, RECENT_LIMIT),
    }


# ---- Stock page ----


def stock_strategies(conn: psycopg.Connection, exchange: str, symbol: str) -> dict[str, Any]:
    """Today's pick or the failed gate per horizon for one stock (raises ListingNotFound)."""
    listing = require_listing(conn, exchange, symbol)
    inputs = stock.load_inputs(conn, listing["listing_id"], listing["symbol"])
    result = stock.current(inputs) or {"as_of": None, "regime": None, "horizons": {}, "setups": []}
    if not result["horizons"]:
        reason = {"reason": "No price history yet", "factors": []}
        result["horizons"] = {h: {"pick": None, "rejection": reason} for h in HORIZONS}
    return {"exchange": listing["exchange"], "symbol": listing["symbol"], **result}


# Finished backtests per (listing, last bar): a full-history run takes ~20 s, and a new bar
# changes the answer. Per process (each uvicorn worker keeps its own).
_BACKTEST_CACHE: OrderedDict[tuple, list[dict]] = OrderedDict()
_BACKTEST_CACHE_SIZE = 32
_cache_lock = threading.Lock()


def _jsonable(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):  # numpy scalars
        return _jsonable(value.item())
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def stock_backtest(conn: psycopg.Connection, exchange: str, symbol: str) -> Iterator[str]:
    """NDJSON lines (start, progress..., done) of every strategy's full-history backtest.

    Loads its data before returning, so the stream itself never touches `conn` (which goes back
    to the pool once streaming starts). A cached run replays at once with "cached": true.
    """
    listing = require_listing(conn, exchange, symbol)
    inputs = stock.load_inputs(conn, listing["listing_id"], listing["symbol"])
    key = (listing["listing_id"], inputs.bars.index[-1] if not inputs.bars.empty else None)
    with _cache_lock:
        cached = _BACKTEST_CACHE.get(key)
        if cached is not None:
            _BACKTEST_CACHE.move_to_end(key)

    def lines() -> Iterator[str]:
        if cached is not None:
            for event in cached:
                yield json.dumps({**event, "cached": True}) + "\n"
            return
        events = []
        for event in stock.backtest_events(inputs):
            event = _jsonable(event)
            events.append(event)
            yield json.dumps(event) + "\n"
        with _cache_lock:
            _BACKTEST_CACHE[key] = events
            while len(_BACKTEST_CACHE) > _BACKTEST_CACHE_SIZE:
                _BACKTEST_CACHE.popitem(last=False)

    return lines()
