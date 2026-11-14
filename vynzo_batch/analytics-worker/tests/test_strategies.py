"""Named swing setups on synthetic daily bars: each strategy fires on its textbook shape."""

import numpy as np
import pandas as pd
import pytest
from analytics_worker.opportunities.engine import RECIPES
from analytics_worker.opportunities.features import compute_features
from analytics_worker.opportunities.levels import find_levels
from analytics_worker.opportunities.strategies import (
    MAX_STOP_ATR,
    MIN_STOP_ATR,
    STRATEGIES,
    detect_setups,
)


def _bars(closes, *, volume=1_000_000.0, last_volume=None, last=None, wick=0.004, seed=1):
    """Daily bars from closes; open = previous close. ``last`` overrides today's OHLC."""
    closes = np.asarray(closes, dtype=float)
    rng = np.random.default_rng(seed)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    jitter = 1 + np.abs(rng.normal(0, wick / 2, len(closes)))
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * (1 + wick) * jitter,
            "low": np.minimum(opens, closes) * (1 - wick) / jitter,
            "close": closes,
            "volume": np.full(len(closes), volume),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="B", tz="UTC"),
    )
    if last_volume is not None:
        frame.iloc[-1, frame.columns.get_loc("volume")] = last_volume
    if last is not None:
        for col, value in last.items():
            frame.iloc[-1, frame.columns.get_loc(col)] = value
    return frame


def _path(start, *legs, noise=0.0, seed=2):
    """Piecewise-linear closes: each leg is (bars, end price)."""
    rng = np.random.default_rng(seed)
    out, price = [], start
    for n, end in legs:
        out += list(np.linspace(price, end, n + 1)[1:])
        price = end
    closes = np.array([start, *out])
    return closes * (1 + rng.normal(0, noise, len(closes)))


def _setups(bars, benchmark=None):
    f = compute_features(bars, benchmark)
    swing = RECIPES["swing"]
    levels = find_levels(bars, k=swing.pivot_k, lookback=swing.pivot_lookback, atr=f.atr14)
    return f, detect_setups(bars, f, levels)


def _fired(bars, key, direction="BUY", benchmark=None):
    _, setups = _setups(bars, benchmark)
    return [s for s in setups if s.key == key and s.direction == direction]


def _first_bar_where(closes, key, direction="BUY", start=60, **kw):
    """Shortest prefix of ``closes`` on whose last bar ``key`` fires (walk-forward search)."""
    for i in range(start, len(closes) + 1):
        if _fired(_bars(closes[:i], **kw), key, direction):
            return i
    return None


def test_catalogue_names_the_ten_strategies():
    assert len(STRATEGIES) == 10
    assert all(s.name and s.description for s in STRATEGIES.values())


def test_trend_pullback_to_the_rising_21_ema():
    closes = _path(100, (150, 180), (5, 172), (1, 175))
    hit = _fired(_bars(closes), "trend_pullback")
    assert hit and "21-day EMA" in hit[0].reason


def test_breakout_needs_volume():
    closes = _path(100, (80, 101), noise=0.004)
    closes = np.append(closes, closes[-1] * 1.05)
    assert _fired(_bars(closes, last_volume=2_500_000), "breakout")
    assert not _fired(_bars(closes), "breakout")  # same price move on normal volume


def test_breakdown_is_a_sell():
    closes = _path(100, (80, 99), noise=0.004)
    closes = np.append(closes, closes[-1] * 0.95)
    assert _fired(_bars(closes, last_volume=2_500_000), "breakout", "SELL")


def test_fast_ema_crossover_fires_on_the_cross():
    closes = _path(100, (80, 80), (40, 95))
    i = _first_bar_where(closes, "ma_crossover")
    assert i is not None
    ema9 = pd.Series(closes[:i]).ewm(span=9, adjust=False).mean()
    ema21 = pd.Series(closes[:i]).ewm(span=21, adjust=False).mean()
    assert ema9.iloc[-1] > ema21.iloc[-1] and ema9.iloc[-4] <= ema21.iloc[-4]


def test_rsi_pullback_in_an_uptrend_turns_up():
    closes = _path(100, (120, 150), (4, 144), (1, 146), noise=0.001)
    hit = _fired(_bars(closes), "rsi_pullback")
    assert hit and "turned up" in hit[0].reason


def test_macd_cross_up_fires_after_a_decline():
    closes = _path(100, (60, 85), (30, 95))
    assert _first_bar_where(closes, "macd_momentum") is not None


def test_squeeze_breakout_after_a_quiet_range():
    rng = np.random.default_rng(5)
    noisy = 100 * np.cumprod(1 + rng.normal(0, 0.02, 100))
    quiet = noisy[-1] * (1 + rng.normal(0, 0.001, 40))
    closes = np.concatenate([noisy, quiet, [quiet[-1] * 1.04]])
    assert _fired(_bars(closes, wick=0.001), "squeeze_breakout")


def test_support_bounce_off_a_tested_level():
    closes = _path(100, (40, 100), (20, 92), (15, 104), (15, 93.5))
    base = _bars(closes)
    support = float(base["low"].iloc[55:70].min())
    bars = _bars(
        np.append(closes, 95.5),
        last={"open": 93.6, "low": support + 0.1, "high": 95.7, "close": 95.5},
    )
    hit = _fired(bars, "support_bounce")
    assert hit and "support" in hit[0].reason


def test_relative_strength_leader_vs_a_flat_nifty():
    closes = _path(100, (200, 105), (63, 130), noise=0.002)
    bars = _bars(closes)
    nifty = pd.Series(np.full(len(bars), 20000.0), index=bars.index)
    assert _fired(bars, "relative_strength", benchmark=nifty)
    assert not _fired(bars, "relative_strength")  # no benchmark: no relative strength


def test_volume_surge_on_an_up_day():
    closes = _path(100, (80, 104), noise=0.004)
    closes = np.append(closes, closes[-1] * 1.02)
    hit = _fired(_bars(closes, last_volume=3_000_000), "volume_accumulation")
    assert hit and hit[0].variant == "surge"


@pytest.mark.parametrize(
    ("variant", "legs"),
    [
        ("double_bottom", ((40, 120), (25, 90), (15, 102), (15, 90.5), (12, 101.5), (1, 103.5))),
        (
            "ascending_triangle",
            (
                (30, 92),
                (8, 100),
                (8, 94),
                (8, 100),
                (8, 96),
                (8, 100),
                (6, 98),
                (4, 99.5),
                (1, 101.5),
            ),
        ),
        ("flag", ((60, 100), (8, 118), (6, 113), (1, 119))),
        ("cup_and_handle", ((30, 100), (50, 80), (60, 99.5), (8, 95), (1, 101.5))),
    ],
)
def test_chart_patterns_break_out(variant, legs):
    closes = _path(100, *legs)
    hit = _fired(_bars(closes), "chart_pattern")
    assert hit and hit[0].variant == variant, [s.variant for s in hit]


def test_stops_sit_on_the_losing_side_within_bounds():
    closes = _path(100, (80, 101), noise=0.004)
    closes = np.append(closes, closes[-1] * 1.05)
    f, setups = _setups(_bars(closes, last_volume=2_500_000))
    assert setups
    for s in setups:
        d = 1 if s.direction == "BUY" else -1
        distance = (f.close - s.stop) * d / f.atr14
        assert MIN_STOP_ATR - 1e-9 <= distance <= MAX_STOP_ATR + 1e-9, s


def test_choppy_tape_has_no_patterns_or_breakouts():
    rng = np.random.default_rng(7)
    closes = 100 + 2 * np.sin(np.arange(260) / 4) + rng.normal(0, 0.3, 260)
    _, setups = _setups(_bars(closes))
    keys = {s.key for s in setups}
    assert not keys & {"chart_pattern", "breakout", "relative_strength", "trend_pullback"}
