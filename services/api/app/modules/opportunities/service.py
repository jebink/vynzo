"""Business use cases for opportunities. Calls the repository; knows nothing about HTTP.

Picks are produced by analytics-worker (opportunities job) from end-of-day bars; this module
only reads and summarises them.
"""

from typing import Any

import psycopg

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
