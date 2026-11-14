"""How a pick played out, from the daily bars after its as_of date. Pure functions.

Rules (conservative, so the track record is not flattered):
- Entry: the first bar within the entry window whose range overlaps the entry range; the fill is
  the bar's open clamped into the range. A gap through the range does not count as filled.
- Exit: the stop if the bar touches it, else the first target if touched. A bar that touches both
  counts as stopped. After ``max_sessions`` bars from as_of the pick expires at that bar's close.
- A pick never filled within the entry window closes as ``not_triggered``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

OUTCOME_VERSION = "outcome-1.0.0"
ENTRY_WINDOW = {"next_session": 1, "swing": 3, "long_term": 10}


@dataclass(frozen=True)
class Outcome:
    status: str  # target_hit | stopped | expired | not_triggered
    entry_at: pd.Timestamp | None = None
    entry_price: float | None = None
    exit_at: pd.Timestamp | None = None
    exit_price: float | None = None
    return_pct: float | None = None
    sessions_held: int | None = None


def evaluate_outcome(pick: Mapping[str, Any], future: pd.DataFrame) -> Outcome | None:
    """``future``: bars strictly after the pick's as_of, ascending. None while the pick is open."""
    d = 1 if pick["direction"] == "BUY" else -1
    lo, hi = float(pick["entry_low"]), float(pick["entry_high"])
    stop, target = float(pick["stop_loss"]), float(pick["targets"][0])
    window = ENTRY_WINDOW[pick["horizon"]]
    max_sessions = int(pick["max_sessions"])

    entry_at = entry_price = None
    entry_index = 0
    for i, (ts, bar) in enumerate(future.iterrows(), start=1):
        if entry_price is None:
            if i > window:
                return Outcome("not_triggered")
            if bar["low"] <= hi and bar["high"] >= lo:
                entry_at, entry_price, entry_index = ts, min(max(float(bar["open"]), lo), hi), i
            else:
                continue
        exit_price, status = _exit(bar, d, stop, target)
        if status is None and i >= max_sessions:
            exit_price, status = float(bar["close"]), "expired"
        if status is not None:
            return Outcome(
                status=status,
                entry_at=entry_at,
                entry_price=entry_price,
                exit_at=ts,
                exit_price=exit_price,
                return_pct=d * (exit_price - entry_price) / entry_price * 100,
                sessions_held=i - entry_index + 1,
            )
    if entry_price is None and len(future) >= window:
        return Outcome("not_triggered")
    return None


def _exit(bar: pd.Series, d: int, stop: float, target: float) -> tuple[float | None, str | None]:
    hit_stop = bar["low"] <= stop if d > 0 else bar["high"] >= stop
    if hit_stop:
        return stop, "stopped"
    hit_target = bar["high"] >= target if d > 0 else bar["low"] <= target
    if hit_target:
        return target, "target_hit"
    return None, None
