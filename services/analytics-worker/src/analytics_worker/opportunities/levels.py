"""Support and resistance from swing pivots."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Levels:
    supports: list[float]  # below the close, nearest first
    resistances: list[float]  # above the close, nearest first


def _merge(levels: list[float], tolerance: float) -> list[float]:
    """Collapse levels closer than ``tolerance`` into their average (sorted ascending)."""
    merged: list[list[float]] = []
    for level in sorted(levels):
        if merged and level - merged[-1][-1] <= tolerance:
            merged[-1].append(level)
        else:
            merged.append([level])
    return [sum(group) / len(group) for group in merged]


def pivots(highs: np.ndarray, lows: np.ndarray, k: int) -> tuple[list[int], list[int]]:
    """Indices of pivot highs and pivot lows, ascending.

    A pivot high is a bar whose high is the highest of the ``k`` bars on each side (lows
    likewise). The last ``k`` bars cannot be confirmed as pivots.
    """
    pivot_highs, pivot_lows = [], []
    for i in range(k, len(highs) - k):
        segment = slice(i - k, i + k + 1)
        if highs[i] == highs[segment].max():
            pivot_highs.append(i)
        if lows[i] == lows[segment].min():
            pivot_lows.append(i)
    return pivot_highs, pivot_lows


def find_levels(bars: pd.DataFrame, *, k: int, lookback: int, atr: float, keep: int = 3) -> Levels:
    """Support and resistance from the ``pivots`` of the last ``lookback`` bars.

    Pivots within 0.5 ATR are merged. A fresh breakout has no resistance above it until a
    new pivot forms.
    """
    window = bars.iloc[-lookback:]
    highs, lows = window["high"].to_numpy(), window["low"].to_numpy()
    high_idx, low_idx = pivots(highs, lows, k)
    pivot_highs = [float(highs[i]) for i in high_idx]
    pivot_lows = [float(lows[i]) for i in low_idx]
    close = float(bars["close"].iloc[-1])
    tolerance = 0.5 * atr if atr > 0 else 0.0
    supports = [x for x in _merge(pivot_lows, tolerance) if x < close]
    resistances = [x for x in _merge(pivot_highs, tolerance) if x > close]
    return Levels(
        supports=sorted(supports, reverse=True)[:keep],
        resistances=sorted(resistances)[:keep],
    )
