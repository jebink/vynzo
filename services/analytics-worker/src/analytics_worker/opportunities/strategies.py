"""Named swing setups: ten common swing-trading strategies, detected at the last daily bar.

Pure functions over bars up to (and including) the session being scored, so the backtest can
replay them without look-ahead. Each detector returns the setups it sees, BUY and/or SELL,
with a one-line reason and the strategy's own stop (where the setup is proven wrong), kept
between MIN_STOP_ATR and MAX_STOP_ATR from the close.

The engine attaches the setups that agree with a swing pick to that pick; the backtest also
trades each setup on its own (`backtest.setup_trade`) to measure every strategy separately.
Chart patterns are detected on the BUY side only (flag, cup and handle, double bottom,
ascending triangle). Sector-relative strength needs sector data and is not included yet.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analytics_worker.indicators.ta import ema, macd, rsi
from analytics_worker.opportunities.features import VOLUME_ANOMALY, Features, finite
from analytics_worker.opportunities.levels import Levels, pivots

MIN_STOP_ATR = 1.0
MAX_STOP_ATR = 3.0
PIVOT_K = 3  # chart-pattern swing points: highest/lowest of 3 bars on each side


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    description: str


@dataclass(frozen=True)
class Setup:
    key: str  # a STRATEGIES key
    direction: str  # BUY | SELL
    reason: str
    stop: float
    variant: str = ""  # e.g. which crossover or chart pattern

    def as_json(self) -> dict:
        return {"key": self.key, "variant": self.variant, "reason": self.reason}


STRATEGIES: dict[str, Strategy] = {
    s.key: s
    for s in (
        Strategy(
            "trend_pullback",
            "Trend pullback",
            "In an uptrend, the price dipped to the rising 21-day EMA and bounced.",
        ),
        Strategy(
            "breakout",
            "Breakout",
            "Closed above the 20-day high on at least 1.5× normal volume.",
        ),
        Strategy(
            "ma_crossover",
            "Moving-average crossover",
            "The 9-day EMA crossed the 21-day EMA, or the 50-day crossed the 200-day.",
        ),
        Strategy(
            "rsi_pullback",
            "RSI pullback",
            "In an uptrend, RSI(14) dipped to 38–50 and turned back up.",
        ),
        Strategy(
            "macd_momentum",
            "MACD momentum",
            "The MACD line crossed its signal line within the last two sessions.",
        ),
        Strategy(
            "squeeze_breakout",
            "Bollinger squeeze breakout",
            "Bollinger bands left a 120-day narrow and the price broke out of the quiet range.",
        ),
        Strategy(
            "support_bounce",
            "Support bounce",
            "The price tested a support level and closed strongly off it.",
        ),
        Strategy(
            "relative_strength",
            "Relative-strength leader",
            "Beat NIFTY by 10+ points over 63 sessions and is still leading over 20.",
        ),
        Strategy(
            "volume_accumulation",
            "Volume surge / accumulation",
            "An up day on 2× normal volume, or OBV rising while the price held steady.",
        ),
        Strategy(
            "chart_pattern",
            "Chart pattern breakout",
            "Broke out of a flag, cup and handle, double bottom or ascending triangle.",
        ),
    )
}


@dataclass(frozen=True)
class _Context:
    f: Features
    levels: Levels
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    ema9: np.ndarray
    ema21: np.ndarray
    ema50: np.ndarray
    ema200: np.ndarray | None
    rsi: np.ndarray
    macd_line: np.ndarray
    macd_hist: np.ndarray

    @property
    def atr(self) -> float:
        return self.f.atr14


def _stop(c: _Context, d: int, natural: float) -> float:
    """``natural`` stop pulled to between MIN_STOP_ATR and MAX_STOP_ATR from the close."""
    distance = (c.f.close - natural) * d
    distance = min(max(distance, MIN_STOP_ATR * c.atr), MAX_STOP_ATR * c.atr)
    return c.f.close - d * distance


def _swing_extreme(c: _Context, d: int, bars: int) -> float:
    """Lowest low (BUY) or highest high (SELL) of the last ``bars`` bars, 0.25 ATR beyond."""
    if d > 0:
        return float(c.low[-bars:].min()) - 0.25 * c.atr
    return float(c.high[-bars:].max()) + 0.25 * c.atr


def _word(d: int, up: str, down: str) -> str:
    return up if d > 0 else down


# ---- Detectors: each returns 0..2 setups ----


def trend_pullback(c: _Context) -> list[Setup]:
    out = []
    f = c.f
    for d in (1, -1):
        trend = (
            (c.ema21[-1] - c.ema50[-1]) * d > 0
            and f.ema50_slope_10 * d > 0
            and (f.close - c.ema50[-1]) * d > 0
        )
        if not trend:
            continue
        edge = c.low[-3:] if d > 0 else c.high[-3:]
        touched = any((edge - c.ema21[-3:] - d * 0.25 * c.atr) * d <= 0)
        bounced = (
            (f.close - c.ema21[-1]) * d > 0
            and (f.close - f.prev_close) * d > 0
            and (f.close_location - 0.5) * d >= 0
        )
        if touched and bounced:
            out.append(
                Setup(
                    "trend_pullback",
                    _word(d, "BUY", "SELL"),
                    f"Pulled back to the {_word(d, 'rising', 'falling')} 21-day EMA "
                    f"{c.ema21[-1]:.2f} and {_word(d, 'bounced', 'turned down')}",
                    _stop(c, d, _swing_extreme(c, d, 3)),
                )
            )
    return out


def breakout(c: _Context) -> list[Setup]:
    f = c.f
    if not finite(f.rvol20) or f.rvol20 < 1.5:
        return []
    if finite(f.dc20_high) and f.close > f.dc20_high:
        level, d = f.dc20_high, 1
    elif finite(f.dc20_low) and f.close < f.dc20_low:
        level, d = f.dc20_low, -1
    else:
        return []
    return [
        Setup(
            "breakout",
            _word(d, "BUY", "SELL"),
            f"Closed {_word(d, 'above the 20-day high', 'below the 20-day low')} {level:.2f} "
            f"on {f.rvol20:.1f}× normal volume",
            _stop(c, d, level - d * c.atr),
        )
    ]


def _crossed(fast: np.ndarray, slow: np.ndarray, within: int) -> int:
    """+1 if ``fast`` crossed above ``slow`` within the last ``within`` bars, -1 below, else 0."""
    if len(fast) <= within or not (np.isfinite(fast[-within - 1 :]).all()):
        return 0
    before, now = fast[-within - 1] - slow[-within - 1], fast[-1] - slow[-1]
    if before <= 0 < now:
        return 1
    if before >= 0 > now:
        return -1
    return 0


def ma_crossover(c: _Context) -> list[Setup]:
    out = []
    crosses = [("9/21", _crossed(c.ema9, c.ema21, 2), "9-day EMA", "21-day EMA")]
    if c.ema200 is not None:
        crosses.append(("50/200", _crossed(c.ema50, c.ema200, 5), "50-day EMA", "200-day EMA"))
    for variant, d, fast, slow in crosses:
        if d:
            out.append(
                Setup(
                    "ma_crossover",
                    _word(d, "BUY", "SELL"),
                    f"The {fast} crossed {_word(d, 'above', 'below')} the {slow}",
                    _stop(c, d, _swing_extreme(c, d, 10)),
                    variant,
                )
            )
    return out


def rsi_pullback(c: _Context) -> list[Setup]:
    f = c.f
    window = c.rsi[-5:]
    if len(window) < 5 or not np.isfinite(window).all():
        return []
    now, prev = window[-1], window[-2]
    if f.ema50_slope_10 > 0 and f.close > c.ema50[-1]:
        low = window.min()
        if 38 <= low <= 50 and now > prev and now <= 60:
            return [
                Setup(
                    "rsi_pullback",
                    "BUY",
                    f"RSI dipped to {low:.0f} in an uptrend and turned up to {now:.0f}",
                    _stop(c, 1, _swing_extreme(c, 1, 5)),
                )
            ]
    if f.ema50_slope_10 < 0 and f.close < c.ema50[-1]:
        high = window.max()
        if 50 <= high <= 62 and now < prev and now >= 40:
            return [
                Setup(
                    "rsi_pullback",
                    "SELL",
                    f"RSI bounced to {high:.0f} in a downtrend and turned down to {now:.0f}",
                    _stop(c, -1, _swing_extreme(c, -1, 5)),
                )
            ]
    return []


def macd_momentum(c: _Context) -> list[Setup]:
    hist = c.macd_hist
    if len(hist) < 3 or not np.isfinite(hist[-3:]).all():
        return []
    if hist[-1] > 0 and min(hist[-3], hist[-2]) <= 0:
        d = 1
    elif hist[-1] < 0 and max(hist[-3], hist[-2]) >= 0:
        d = -1
    else:
        return []
    zero = "below" if c.macd_line[-1] < 0 else "above"
    return [
        Setup(
            "macd_momentum",
            _word(d, "BUY", "SELL"),
            f"MACD crossed {_word(d, 'above', 'below')} its signal line ({zero} the zero line)",
            _stop(c, d, _swing_extreme(c, d, 10)),
        )
    ]


def squeeze_breakout(c: _Context) -> list[Setup]:
    if not c.f.squeeze_release or len(c.close) < 11:
        return []
    prior = c.close[-11:-1]
    if c.f.close > prior.max():
        d = 1
    elif c.f.close < prior.min():
        d = -1
    else:
        return []
    return [
        Setup(
            "squeeze_breakout",
            _word(d, "BUY", "SELL"),
            f"Broke {_word(d, 'up', 'down')} out of a Bollinger squeeze "
            "(bands at a 120-day narrow)",
            _stop(c, d, _swing_extreme(c, d, 10)),
        )
    ]


def support_bounce(c: _Context) -> list[Setup]:
    f, near = c.f, 0.5 * c.atr
    out = []
    if c.levels.supports:
        s = c.levels.supports[0]
        if abs(f.low - s) <= near and f.close > s and f.close > f.open and f.close_location >= 0.6:
            out.append(
                Setup(
                    "support_bounce",
                    "BUY",
                    f"Tested support {s:.2f} and closed strongly off it",
                    _stop(c, 1, s - near),
                )
            )
    if c.levels.resistances:
        r = c.levels.resistances[0]
        if abs(f.high - r) <= near and f.close < r and f.close < f.open and f.close_location <= 0.4:
            out.append(
                Setup(
                    "support_bounce",
                    "SELL",
                    f"Rejected at resistance {r:.2f} and closed weak",
                    _stop(c, -1, r + near),
                )
            )
    return out


def relative_strength(c: _Context) -> list[Setup]:
    f = c.f
    if not (finite(f.rs_63) and finite(f.rs_20)):
        return []
    if f.rs_63 >= 0.10 and f.rs_20 > 0 and f.close > c.ema21[-1] and f.close >= 0.85 * f.high_52w:
        d = 1
    elif f.rs_63 <= -0.10 and f.rs_20 < 0 and f.close < c.ema21[-1] and f.close <= 1.15 * f.low_52w:
        d = -1
    else:
        return []
    return [
        Setup(
            "relative_strength",
            _word(d, "BUY", "SELL"),
            f"{_word(d, 'Leader', 'Laggard')}: {_word(d, 'beat', 'trailed')} NIFTY by "
            f"{abs(f.rs_63) * 100:.0f} pts over 63 sessions and "
            f"{abs(f.rs_20) * 100:.1f} over 20",
            _stop(c, d, _swing_extreme(c, d, 10)),
        )
    ]


def volume_accumulation(c: _Context) -> list[Setup]:
    f = c.f
    out = []
    if finite(f.rvol20) and 2.0 <= f.rvol20 <= VOLUME_ANOMALY and f.close != f.prev_close:
        d = 1 if f.close > f.prev_close else -1
        if (f.close_location - 0.5) * d >= 0.1:
            out.append(
                Setup(
                    "volume_accumulation",
                    _word(d, "BUY", "SELL"),
                    f"{_word(d, 'Up', 'Down')} day on {f.rvol20:.1f}× normal volume",
                    _stop(c, d, _swing_extreme(c, d, 10)),
                    "surge",
                )
            )
    if not out and finite(f.obv_slope_20) and abs(f.obv_slope_20) >= 0.15 and abs(f.ret_20) <= 0.03:
        d = 1 if f.obv_slope_20 > 0 else -1
        out.append(
            Setup(
                "volume_accumulation",
                _word(d, "BUY", "SELL"),
                f"OBV {_word(d, 'rising', 'falling')} while the price held steady over 20 sessions "
                f"({_word(d, 'accumulation', 'distribution')})",
                _stop(c, d, _swing_extreme(c, d, 10)),
                "obv",
            )
        )
    return out


# ---- Chart patterns (BUY side). Each returns (variant, pivot level, natural stop) or None. ----


def _broke_above(c: _Context, level: float) -> bool:
    """Today's close is the first close above ``level``."""
    return c.close[-1] > level >= c.close[-2]


def _bull_flag(c: _Context) -> tuple[str, float, float] | None:
    n = len(c.close)
    for p in range(n - 4, max(n - 14, 11) - 1, -1):  # pole top 3..12 bars before today
        pole_low = float(c.low[p - 10 : p].min())
        top = float(c.high[p])
        if top < float(c.high[p - 10 : n - 1].max()) or top < pole_low * 1.10:
            continue
        if top - pole_low < 4 * c.atr:
            continue
        flag_high = float(c.high[p + 1 : n - 1].max())
        flag_low = float(c.low[p + 1 : n - 1].min())
        if top - flag_low <= 0.5 * (top - pole_low) and _broke_above(c, flag_high):
            return "flag", flag_high, flag_low - 0.25 * c.atr
    return None


def _double_bottom(c: _Context) -> tuple[str, float, float] | None:
    window = 80
    low, high = c.low[-window:], c.high[-window:]
    _, lows = pivots(high, low, PIVOT_K)
    for b in reversed(lows):
        for a in reversed([i for i in lows if i <= b - 10]):
            la, lb = low[a], low[b]
            if abs(la - lb) > 0.03 * min(la, lb) or low[a : b + 1].min() < min(la, lb) * 0.995:
                continue
            neckline = float(high[a : b + 1].max())
            if neckline - max(la, lb) < 2 * c.atr:
                continue
            if c.close[-window + b : -1].max() <= neckline and _broke_above(c, neckline):
                return "double_bottom", neckline, float(min(la, lb)) - 0.25 * c.atr
        break  # only the latest pivot low can complete the pattern
    return None


def _ascending_triangle(c: _Context) -> tuple[str, float, float] | None:
    window = 60
    low, high = c.low[-window:], c.high[-window:]
    highs, lows = pivots(high, low, PIVOT_K)
    if len(highs) < 2:
        return None
    tops = highs[-3:] if len(highs) >= 3 else highs[-2:]
    top_values = high[tops]
    resistance = float(top_values.max())
    if top_values.min() < resistance * 0.985 or tops[-1] - tops[0] < 15:
        return None
    rising = [i for i in lows if i > tops[0]]
    if len(rising) < 2 or not all(
        low[x] < low[y] for x, y in zip(rising, rising[1:], strict=False)
    ):
        return None
    if _broke_above(c, resistance):
        return "ascending_triangle", resistance, float(low[rising[-1]]) - 0.25 * c.atr
    return None


def _cup_and_handle(c: _Context) -> tuple[str, float, float] | None:
    n = len(c.close)
    if n < 150:
        return None
    start = n - 150
    left = start + int(np.argmax(c.high[start : n - 40]))
    bottom = left + int(np.argmax(-c.low[left : n - 6]))
    rim_l, cup_low = float(c.high[left]), float(c.low[bottom])
    depth = (rim_l - cup_low) / rim_l
    if not 0.12 <= depth <= 0.35 or bottom - left < 10:
        return None
    right = bottom + int(np.argmax(c.high[bottom : n - 1]))
    rim_r = float(c.high[right])
    handle = n - 1 - right
    if right - bottom < 10 or rim_r < 0.95 * rim_l or not 5 <= handle <= 20:
        return None
    handle_low = float(c.low[right + 1 : n - 1].min())
    if rim_r - handle_low > 0.5 * (rim_l - cup_low):
        return None
    if _broke_above(c, rim_r):
        return "cup_and_handle", rim_r, handle_low - 0.25 * c.atr
    return None


_PATTERN_NAMES = {
    "cup_and_handle": "cup and handle",
    "double_bottom": "double bottom",
    "ascending_triangle": "ascending triangle",
    "flag": "flag",
}


def chart_pattern(c: _Context) -> list[Setup]:
    # Most specific first: rising lows within 3% would also read as a double bottom.
    for find in (_cup_and_handle, _ascending_triangle, _double_bottom, _bull_flag):
        found = find(c)
        if found:
            variant, level, natural = found
            return [
                Setup(
                    "chart_pattern",
                    "BUY",
                    f"Broke out of a {_PATTERN_NAMES[variant]} above {level:.2f}",
                    _stop(c, 1, natural),
                    variant,
                )
            ]
    return []


DETECTORS: tuple[Callable[[_Context], list[Setup]], ...] = (
    trend_pullback,
    breakout,
    ma_crossover,
    rsi_pullback,
    macd_momentum,
    squeeze_breakout,
    support_bounce,
    relative_strength,
    volume_accumulation,
    chart_pattern,
)


def detect_setups(bars: pd.DataFrame, f: Features, levels: Levels) -> list[Setup]:
    """Every strategy setup at the last bar of ``bars``; ``f`` and ``levels`` are for that bar."""
    if not finite(f.atr14) or f.atr14 <= 0 or len(bars) < 30:
        return []
    close = bars["close"]
    line, _, hist = macd(close)
    c = _Context(
        f=f,
        levels=levels,
        open=bars["open"].to_numpy(dtype=float),
        high=bars["high"].to_numpy(dtype=float),
        low=bars["low"].to_numpy(dtype=float),
        close=close.to_numpy(dtype=float),
        ema9=ema(close, 9).to_numpy(),
        ema21=ema(close, 21).to_numpy(),
        ema50=ema(close, 50).to_numpy(),
        ema200=ema(close, 200).to_numpy() if len(bars) >= 220 else None,
        rsi=rsi(close).to_numpy(),
        macd_line=line.to_numpy(),
        macd_hist=hist.to_numpy(),
    )
    setups: list[Setup] = []
    for detect in DETECTORS:
        setups += detect(c)
    return setups
