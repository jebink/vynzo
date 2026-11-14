"""Opportunity scoring: per-horizon factor recipes, confluence, penalties and the trade plan.

Pure functions. Bump CALC_VERSION on any change to the scoring or plan logic: every stored
opportunity records the version that produced it (architecture rule 5).

How a pick is made, per horizon:
1. Six factor groups (trend, momentum, price action, volume, volatility, relative strength)
   each score -1 (bearish) .. +1 (bullish) with a one-line reason. Each horizon uses its own
   inputs and weights: next-session setups lean on today's range and volume, swing on 20-55
   session structure, long-term on the 200-day trend and 6-12 month relative strength.
2. The weighted sum gives the direction. At least MIN_CONFLUENCE groups must agree with it
   (aligned score >= the recipe's `agree`); a single strong indicator is never enough.
3. Score 0-100 = the direction-aligned weighted sum scaled by the recipe's `full_score_at`,
   minus penalties: each conflicting group, a market regime against the trade, excess
   volatility and a poor risk/reward. Illiquid and penny stocks are excluded outright.
4. Below the recipe's `watch_score` nothing is emitted. "actionable" needs `actionable_score`,
   the recipe's minimum risk/reward and at least medium confidence; the rest is "watch".
5. Backtest rules (opp-1.4.0, walk-forward 2018-2026 on dev data; decided on 2018-2022, confirmed
   on 2023-2026): SELL picks lost money in both periods and are always "watch"; BUYs made while
   the market regime is bearish lagged NIFTY in both periods and are never "actionable".

Long-term factors (trend, momentum, relative strength) are correlated: in a rising market most
stocks agree on all of them. So long-term uses a stricter `agree`, an unscaled score and higher
floors. Thresholds are fixed per recipe, not fitted to one day's distribution.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from analytics_worker.opportunities.features import (
    VOLUME_ANOMALY,
    Features,
    clip,
    compute_features,
    finite,
)
from analytics_worker.opportunities.levels import Levels, find_levels
from analytics_worker.opportunities.regime import Regime
from analytics_worker.opportunities.strategies import Setup, detect_setups

CALC_VERSION = "opp-1.5.0"

MIN_CONFLUENCE = 3
MIN_PRICE = 20.0
ACTIONABLE_DIRECTIONS = ("BUY",)  # SELL: monitor only until a backtest shows an edge (rule 5)
CONFIDENCE_ORDER = ("low", "medium", "high")


@dataclass(frozen=True)
class Factor:
    group: str
    score: float  # -1 bearish .. +1 bullish
    reason: str


@dataclass(frozen=True)
class Recipe:
    horizon: str
    weights: dict[str, float]
    factors: Callable[[Features], list[Factor]]
    min_bars: int
    min_traded_value: float  # rupees per day, 20-day average
    max_atr_pct: float
    rr_min: float
    pivot_k: int
    pivot_lookback: int
    holding_period: str
    max_sessions: int
    confidence_cap: str
    t1_r: float  # default first target, in multiples of the risk
    t2_r: float
    full_score_at: float  # aligned weighted sum that maps to a score of 100
    allow_actionable: bool  # False: the horizon only ever produces "watch" picks
    agree: float  # a group "agrees" with the direction at this aligned score or more
    watch_score: int
    actionable_score: int
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Opportunity:
    horizon: str
    direction: str  # BUY | SELL
    status: str  # actionable | watch
    score: int
    confidence: str
    price: float
    entry_low: float
    entry_high: float
    stop_loss: float
    targets: list[float]
    risk_reward: float
    holding_period: str
    max_sessions: int
    supports: list[float]
    resistances: list[float]
    reasons: list[str]
    factors: list[Factor]
    risks: list[str]
    invalidation: list[str]
    inputs: dict = field(default_factory=dict)
    setups: list[Setup] = field(default_factory=list)  # named strategies agreeing (swing)


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _sentence(text: str) -> str:
    """Upper-case the first letter only (str.capitalize would lower-case "NIFTY", "ATR")."""
    return text[:1].upper() + text[1:]


# ---- Factor groups per horizon ----


def _relative_strength(rs: float, label: str, scale: float) -> Factor:
    if not finite(rs):
        return Factor("relative_strength", 0.0, "Relative strength vs NIFTY unavailable")
    word = "outperformed" if rs > 0 else "underperformed"
    return Factor(
        "relative_strength",
        clip(rs / scale),
        f"{_sentence(word)} NIFTY by {abs(rs) * 100:.1f} pts over {label}",
    )


def _volume_today(f: Features, scale: float) -> Factor:
    day = _sign(f.close - f.prev_close)
    if not finite(f.rvol20) or f.rvol20 < 1.3 or day == 0:
        return Factor("volume", 0.0, f"Volume {f.rvol20:.1f}× its 20-day average (no spike)")
    word = "up" if day > 0 else "down"
    if f.rvol20 > VOLUME_ANOMALY:
        return Factor(
            "volume",
            day * 0.3,
            f"Volume {f.rvol20:.0f}× its 20-day average on an {word} day "
            "(unusually high: possibly a block deal or a data error)",
        )
    return Factor(
        "volume",
        day * clip((f.rvol20 - 1.0) / scale, 0, 1),
        f"Volume {f.rvol20:.1f}× its 20-day average on an {word} day",
    )


def next_session_factors(f: Features) -> list[Factor]:
    # Price action: today's range expansion, where it closed, gaps and 20-day breaks.
    pa, pa_why = 0.0, []
    if finite(f.range_atr) and f.range_atr >= 1.2:
        if f.close_location >= 0.8:
            pa += 0.5
            pa_why.append(f"wide-range day ({f.range_atr:.1f} ATR) closing near the high")
        elif f.close_location <= 0.2:
            pa -= 0.5
            pa_why.append(f"wide-range day ({f.range_atr:.1f} ATR) closing near the low")
    if finite(f.dc20_high) and f.close > f.dc20_high:
        pa += 0.4
        pa_why.append(f"closed above the 20-day high {f.dc20_high:.2f}")
    elif finite(f.dc20_low) and f.close < f.dc20_low:
        pa -= 0.4
        pa_why.append(f"closed below the 20-day low {f.dc20_low:.2f}")
    if finite(f.gap_pct) and abs(f.gap_pct) >= 1 and _sign(f.gap_pct) == _sign(f.close - f.open):
        pa += 0.2 * _sign(f.gap_pct)
        pa_why.append(f"gap of {f.gap_pct:+.1f}% held through the close")
    price_action = Factor(
        "price_action",
        clip(pa),
        _sentence("; ".join(pa_why)) or "No range expansion or breakout today",
    )

    mom = 0.5 * clip(f.ret_5 / 0.05)
    if finite(f.rsi14) and finite(f.rsi14_prev):
        if 55 <= f.rsi14 <= 75 and f.rsi14 > f.rsi14_prev:
            mom += 0.4
        elif 25 <= f.rsi14 <= 45 and f.rsi14 < f.rsi14_prev:
            mom -= 0.4
    momentum = Factor("momentum", clip(mom), f"RSI {f.rsi14:.0f}, {_pct(f.ret_5)} over 5 sessions")

    if f.close > f.ema9 > f.ema21:
        tr, why = 0.6, "Close above the rising 9/21-day EMAs"
    elif f.close < f.ema9 < f.ema21:
        tr, why = -0.6, "Close below the falling 9/21-day EMAs"
    else:
        tr, why = 0.0, "Short-term EMAs mixed"
    tr += 0.4 * _sign(f.close - f.ema50)
    trend = Factor(
        "trend", clip(tr), f"{why}; {'above' if f.close > f.ema50 else 'below'} the 50-day EMA"
    )

    return [
        price_action,
        _volume_today(f, 2.0),
        momentum,
        trend,
        _relative_strength(f.rs_20, "20 sessions", 0.05),
    ]


def _swing_trend(f: Features) -> Factor:
    tr = (
        0.3 * _sign(f.close - f.ema21)
        + 0.3 * _sign(f.ema21 - f.ema50)
        + 0.2 * _sign(f.ema50_slope_10)
    )
    di = ""
    if finite(f.adx14) and f.adx14 >= 20:
        tr += 0.2 * _sign(f.plus_di - f.minus_di)
        di = f", ADX {f.adx14:.0f} with {'+DI' if f.plus_di > f.minus_di else '-DI'} leading"
    return Factor(
        "trend",
        clip(tr),
        f"Close {'above' if f.close > f.ema21 else 'below'} the 21-day EMA, 21-EMA "
        f"{'above' if f.ema21 > f.ema50 else 'below'} 50-EMA, 50-EMA "
        f"{'rising' if f.ema50_slope_10 > 0 else 'falling'}{di}",
    )


# RSI bands for swing momentum: (low, high, score, note). 45-55 is neutral.
_SWING_RSI_BANDS = (
    (55, 70, 0.5, ""),
    (70, 80, 0.2, " (stretched)"),
    (80, 101, -0.1, " (overbought)"),
    (30, 45, -0.5, ""),
    (-1, 30, -0.2, " (oversold)"),
)


def _swing_momentum(f: Features) -> Factor:
    mom, why = 0.0, f"RSI {f.rsi14:.0f}"
    if finite(f.rsi14):
        for lo, hi, score, note in _SWING_RSI_BANDS:
            if lo <= f.rsi14 < hi:
                mom, why = score, why + note
                break
    if finite(f.macd_hist) and finite(f.macd_hist_prev):
        rising = f.macd_hist > f.macd_hist_prev
        positive = f.macd_hist > 0
        with_trend = rising == positive  # positive and rising, or negative and falling
        mom += (0.5 if with_trend else 0.2) * (1 if positive else -1)
        why += (
            f"; MACD histogram {'positive' if positive else 'negative'} and "
            f"{'rising' if rising else 'falling'}"
        )
    return Factor("momentum", clip(mom), why)


def _swing_price_action(f: Features) -> Factor:
    if finite(f.dc20_high) and f.close > f.dc20_high:
        strong = 0.2 if f.close_location >= 0.7 else 0.0
        return Factor(
            "price_action", clip(0.8 + strong), f"Breakout above the 20-day high {f.dc20_high:.2f}"
        )
    if finite(f.dc20_low) and f.close < f.dc20_low:
        strong = 0.2 if f.close_location <= 0.3 else 0.0
        return Factor(
            "price_action", clip(-0.8 - strong), f"Breakdown below the 20-day low {f.dc20_low:.2f}"
        )
    if f.ema21 > f.ema50 and f.low <= f.ema21 * 1.01 and f.close > f.ema21:
        return Factor("price_action", 0.5, f"Pullback to the rising 21-day EMA {f.ema21:.2f} held")
    if f.ema21 < f.ema50 and f.high >= f.ema21 * 0.99 and f.close < f.ema21:
        return Factor(
            "price_action", -0.5, f"Rally to the falling 21-day EMA {f.ema21:.2f} rejected"
        )
    return Factor("price_action", 0.0, "No breakout or pullback setup")


def _swing_volume(f: Features) -> Factor:
    vol = _volume_today(f, 1.5)
    if not finite(f.obv_slope_20) or abs(f.obv_slope_20) < 0.1:
        return vol
    word = "accumulation" if f.obv_slope_20 > 0 else "distribution"
    return Factor(
        "volume",
        clip(vol.score * 0.6 + 0.4 * _sign(f.obv_slope_20)),
        f"{vol.reason}; OBV shows {word} over 20 sessions",
    )


def _swing_volatility(f: Features) -> Factor:
    if f.squeeze_release:
        return Factor(
            "volatility",
            0.6 * _sign(f.close - f.prev_close),
            "Bollinger squeeze releasing (bands expanding from a 120-day low)",
        )
    return Factor("volatility", 0.0, f"Bollinger width at the {f.bb_width_pctile:.0f}th percentile")


def swing_factors(f: Features) -> list[Factor]:
    return [
        _swing_trend(f),
        _swing_momentum(f),
        _swing_price_action(f),
        _swing_volume(f),
        _swing_volatility(f),
        _relative_strength(f.rs_63, "63 sessions", 0.10),
    ]


def long_term_factors(f: Features) -> list[Factor]:
    tr = (
        0.35 * _sign(f.close - f.ema200)
        + 0.3 * _sign(f.ema50 - f.ema200)
        + 0.35 * _sign(f.ema200_slope_20)
    )
    trend = Factor(
        "trend",
        clip(tr),
        f"Close {'above' if f.close > f.ema200 else 'below'} the 200-day EMA, 50-EMA "
        f"{'above' if f.ema50 > f.ema200 else 'below'} it, 200-EMA "
        f"{'rising' if f.ema200_slope_20 > 0 else 'falling'}",
    )
    momentum = Factor(
        "momentum",
        clip(0.5 * clip(f.ret_126 / 0.25) + 0.5 * clip(f.ret_252 / 0.4)),
        f"{_pct(f.ret_126)} over 6 months, {_pct(f.ret_252)} over 12 months",
    )
    pa, pa_why = 0.0, f"{(f.close / f.high_52w - 1) * 100:.0f}% from the 52-week high"
    if f.close >= 0.95 * f.high_52w and finite(f.dc55_high) and f.close > f.dc55_high:
        pa, pa_why = 0.8, f"Breaking out to new highs near the 52-week high {f.high_52w:.2f}"
    elif f.close >= 0.9 * f.high_52w:
        pa, pa_why = 0.4, f"Within 10% of the 52-week high {f.high_52w:.2f}"
    elif finite(f.dc55_low) and f.close < f.dc55_low:
        pa, pa_why = -0.8, f"Breaking down below the 55-day low {f.dc55_low:.2f}"
    elif f.close <= 1.1 * f.low_52w:
        pa, pa_why = -0.6, f"Within 10% of the 52-week low {f.low_52w:.2f}"
    volume = Factor(
        "volume",
        clip(f.obv_slope_60 / 0.2) if finite(f.obv_slope_60) else 0.0,
        f"OBV {'rising' if f.obv_slope_60 > 0 else 'falling'} over 60 sessions"
        if finite(f.obv_slope_60)
        else "OBV unavailable",
    )
    rs_126 = _relative_strength(f.rs_126, "6 months", 0.2)
    rs_252 = _relative_strength(f.rs_252, "12 months", 0.3)
    relative = Factor(
        "relative_strength",
        clip((rs_126.score + rs_252.score) / 2),
        f"{_sentence(rs_126.reason)}; {rs_252.reason}",
    )
    return [trend, relative, momentum, Factor("price_action", pa, pa_why), volume]


RECIPES: dict[str, Recipe] = {
    "next_session": Recipe(
        horizon="next_session",
        weights={
            "price_action": 0.30,
            "volume": 0.25,
            "momentum": 0.20,
            "trend": 0.15,
            "relative_strength": 0.10,
        },
        factors=next_session_factors,
        min_bars=60,
        min_traded_value=5e7,  # ₹5 crore/day: intraday needs liquidity
        max_atr_pct=6.0,
        rr_min=1.5,
        pivot_k=3,
        pivot_lookback=40,
        holding_period="Next trading session (exit by the close)",
        max_sessions=1,
        confidence_cap="high",
        t1_r=1.5,
        t2_r=2.5,
        full_score_at=0.75,
        # Without intraday data a next-session trigger cannot be confirmed, and a backtest of
        # these setups on daily bars showed no reliable edge: monitor-only until a feed exists.
        allow_actionable=False,
        agree=0.25,
        watch_score=55,
        actionable_score=75,
        notes=(
            "From the last daily close, not live prices: confirm the trigger in the session",
            "Monitor only: next-session setups are not actionable until intraday data is available",
        ),
    ),
    "swing": Recipe(
        horizon="swing",
        weights={
            "trend": 0.25,
            "price_action": 0.20,
            "momentum": 0.20,
            "volume": 0.15,
            "relative_strength": 0.15,
            "volatility": 0.05,
        },
        factors=swing_factors,
        min_bars=120,
        min_traded_value=2e7,  # ₹2 crore/day
        max_atr_pct=5.0,
        rr_min=2.0,
        pivot_k=5,
        pivot_lookback=120,
        holding_period="5–20 trading sessions",
        max_sessions=20,
        confidence_cap="high",
        t1_r=2.0,
        t2_r=3.0,
        full_score_at=0.8,
        allow_actionable=True,
        agree=0.25,
        watch_score=55,
        actionable_score=75,
    ),
    "long_term": Recipe(
        horizon="long_term",
        weights={
            "trend": 0.30,
            "relative_strength": 0.25,
            "momentum": 0.20,
            "price_action": 0.15,
            "volume": 0.10,
        },
        factors=long_term_factors,
        min_bars=260,
        min_traded_value=1e7,  # ₹1 crore/day
        max_atr_pct=4.5,
        rr_min=2.0,
        pivot_k=10,
        pivot_lookback=250,
        holding_period="3–12 months",
        max_sessions=250,
        confidence_cap="medium",  # technical only until fundamentals are ingested
        t1_r=2.0,
        t2_r=4.0,
        full_score_at=1.0,
        allow_actionable=True,
        agree=0.4,
        watch_score=70,
        actionable_score=85,
        notes=("Fundamentals not yet included: technical trend and relative strength only",),
    ),
}


# ---- Combining factors ----


@dataclass(frozen=True)
class Confluence:
    direction: int  # +1 BUY, -1 SELL, 0 none
    aligned: float  # weighted sum in the trade direction, 0..1
    agreeing: list[Factor]
    conflicting: list[Factor]


def confluence(weights: dict[str, float], factors: list[Factor], agree: float = 0.25) -> Confluence:
    raw = sum(weights.get(x.group, 0.0) * x.score for x in factors)
    direction = _sign(raw)
    used = [x for x in factors if weights.get(x.group, 0.0) > 0]
    agreeing = [x for x in used if x.score * direction >= agree]
    conflicting = [x for x in used if x.score * direction <= -agree]
    agreeing.sort(key=lambda x: -weights[x.group] * abs(x.score))
    return Confluence(direction, abs(raw), agreeing, conflicting)


def _confidence(score: int, c: Confluence, regime_against: bool, recipe: "Recipe") -> str:
    top = recipe.actionable_score + 10
    if score >= top and len(c.agreeing) >= 4 and not c.conflicting and not regime_against:
        level = "high"
    elif score >= recipe.actionable_score - 5 and len(c.conflicting) <= 1:
        level = "medium"
    else:
        level = "low"
    return min(level, recipe.confidence_cap, key=CONFIDENCE_ORDER.index)


# ---- Trade plan ----


@dataclass(frozen=True)
class Plan:
    entry_low: float
    entry_high: float
    stop: float
    targets: list[float]
    risk_reward: float


def _target(
    entry: float,
    risk: float,
    d: int,
    levels: list[float],
    default_r: float,
    after: float,
    atr: float,
) -> float:
    """The first level beyond ``after`` within 1.5× the default distance, else the default."""
    default = entry + d * default_r * risk
    for level in levels:
        if (level - after) * d > 0 and abs(level - entry) <= 1.5 * default_r * risk:
            return level - d * 0.1 * atr  # just before the level
    return default


def trade_plan(recipe: Recipe, f: Features, levels: Levels, d: int) -> Plan:
    atr = f.atr14
    if recipe.horizon == "next_session":
        # Trigger beyond today's extreme in the trade direction.
        lo, hi = (f.high, f.high + 0.15 * atr) if d > 0 else (f.low - 0.15 * atr, f.low)
        entry = (lo + hi) / 2
        stop = entry - d * 0.6 * atr
    else:
        below, above = (0.25, 0.1) if recipe.horizon == "swing" else (0.5, 0.2)
        lo, hi = (
            (f.close - below * atr, f.close + above * atr)
            if d > 0
            else (f.close - above * atr, f.close + below * atr)
        )
        entry = (lo + hi) / 2
        min_r, max_r, default_r = (1.0, 2.5, 1.5) if recipe.horizon == "swing" else (2.0, 4.0, 3.0)
        guard = levels.supports if d > 0 else levels.resistances
        level = next((x for x in guard if (entry - x) * d > 0), None)
        distance = abs(entry - level) + 0.1 * atr if level is not None else default_r * atr
        distance = min(max(distance, min_r * atr), max_r * atr)
        stop = entry - d * distance
    risk = abs(entry - stop)
    ahead = levels.resistances if d > 0 else levels.supports
    edge = hi if d > 0 else lo
    t1 = _target(entry, risk, d, ahead, recipe.t1_r, edge, atr)
    t2 = _target(entry, risk, d, ahead, recipe.t2_r, t1 + d * 0.5 * risk, atr)
    if (t2 - t1) * d <= 0:
        t2 = entry + d * max(recipe.t2_r, abs(t1 - entry) / risk + 1) * risk
    rr = abs(t1 - entry) / risk if risk > 0 else 0.0
    return Plan(lo, hi, stop, [t1, t2], rr)


# ---- Evaluate ----


def _blocking_risks(direction: str, regime: Regime) -> list[str]:
    """Risk lines that also make a pick non-actionable, whatever its score.

    - SELL: lost money in both backtest periods (``ACTIONABLE_DIRECTIONS``).
    - NIFTY's short-term direction against the trade: the slow regime lags turns by weeks.
    Two more blockers already have their risk line: a stretched entry, and the slow regime
    against the trade (those BUYs lagged NIFTY in both backtest periods).
    """
    out = []
    if direction not in ACTIONABLE_DIRECTIONS:
        out.append(
            f"Monitor only: {direction} setups lost money in the 2018–2026 backtest; "
            "treat this as a warning to avoid or reduce, not a trade"
        )
    if regime.short_term * (1 if direction == "BUY" else -1) < -0.25:
        out.append(
            f"NIFTY's short-term direction is against this {direction}: "
            "wait for the market to confirm"
        )
    return out


@dataclass(frozen=True)
class Rejection:
    """Why a listing made no pick for a horizon: the first gate it failed, for the stock page."""

    reason: str
    factors: list[Factor] = field(default_factory=list)
    score: int | None = None  # set when it failed only on the final score


def evaluate(
    horizon: str,
    f: Features,
    levels: Levels,
    regime: Regime,
    setups: list[Setup] | tuple[Setup, ...] = (),
) -> Opportunity | None:
    """The opportunity for one listing and horizon, or None when it does not qualify.

    ``setups`` (named strategies, `strategies.py`) that agree with the pick's direction are
    attached to it. They label the pick; they do not change its score or status.
    """
    result = assess(horizon, f, levels, regime, setups)
    return result if isinstance(result, Opportunity) else None


def assess(
    horizon: str,
    f: Features,
    levels: Levels,
    regime: Regime,
    setups: list[Setup] | tuple[Setup, ...] = (),
) -> Opportunity | Rejection:
    """`evaluate`, but a non-pick says which gate it failed."""
    recipe = RECIPES[horizon]
    if f.bars < recipe.min_bars or not finite(f.atr14) or f.atr14 <= 0:
        return Rejection(f"Not enough history: {f.bars} sessions, needs {recipe.min_bars}")
    if not _tradeable(f, recipe):
        if f.close < MIN_PRICE:
            return Rejection(f"Price {f.close:.2f} is below the ₹{MIN_PRICE:g} floor")
        return Rejection(
            f"Too illiquid: about ₹{f.traded_value_20 / 1e7:.1f} crore traded per day, "
            f"needs ₹{recipe.min_traded_value / 1e7:.1f} crore"
        )
    factors = recipe.factors(f)
    c = confluence(recipe.weights, factors, recipe.agree)
    if c.direction == 0 or len(c.agreeing) < MIN_CONFLUENCE:
        return Rejection(
            f"Only {len(c.agreeing)} of {len(factors)} factor groups agree on a direction; "
            f"needs {MIN_CONFLUENCE}",
            factors,
        )

    d = c.direction
    plan = trade_plan(recipe, f, levels, d)
    score = 100 * min(1.0, c.aligned / recipe.full_score_at)
    risks: list[str] = []
    score -= 8 * len(c.conflicting)
    risks += [f"Conflicting {x.group.replace('_', ' ')}: {x.reason}" for x in c.conflicting]
    regime_against = regime.score * d <= -0.3
    if regime_against:
        score -= round(20 * abs(regime.score))
        risks.append(f"Market regime is {regime.label}, against this {'BUY' if d > 0 else 'SELL'}")
    elif regime.score * d >= 0.3:
        score += 5
    extended = _extension(recipe.horizon, f, d)
    if extended:
        score -= 10
        risks.append(extended)
    if f.atr_pct > recipe.max_atr_pct:
        score -= 10
        risks.append(f"High volatility: daily ATR is {f.atr_pct:.1f}% of the price")
    if plan.risk_reward < recipe.rr_min:
        # 15 points at the minimum, up to 35 as risk/reward approaches 0.
        score -= 15 + 20 * (1 - plan.risk_reward / recipe.rr_min)
        risks.append(
            f"Risk/reward {plan.risk_reward:.1f} is below {recipe.rr_min:.1f}: "
            "a nearby level limits the move"
        )
    if f.traded_value_20 < 2 * recipe.min_traded_value:
        risks.append(f"Thin liquidity: about ₹{f.traded_value_20 / 1e7:.1f} crore traded per day")
    score = int(max(0, min(100, round(score))))
    if f.rvol20 > VOLUME_ANOMALY:
        risks.append(f"Volume was {f.rvol20:.0f}× normal: check for a block deal or a data error")
    if score < recipe.watch_score:
        return Rejection(
            f"Score {score} after penalties is below the {recipe.watch_score} floor"
            + (f" ({'; '.join(risks[:2])})" if risks else ""),
            factors,
            score,
        )

    confidence = _confidence(score, c, regime_against, recipe)
    direction = "BUY" if d > 0 else "SELL"
    blockers = _blocking_risks(direction, regime)
    risks += blockers
    actionable = (
        recipe.allow_actionable
        and not (blockers or extended or regime_against)
        and score >= recipe.actionable_score
        and plan.risk_reward >= recipe.rr_min
        and CONFIDENCE_ORDER.index(confidence) >= CONFIDENCE_ORDER.index("medium")
    )
    risks.append("No earnings or events calendar yet: check for results or corporate actions first")
    risks += list(recipe.notes)

    reasons = [x.reason for x in c.agreeing[:4]]
    if regime.score * d >= 0.3:
        reasons.append(f"Market regime {regime.label}: {regime.notes[0]}")

    return Opportunity(
        horizon=horizon,
        direction=direction,
        status="actionable" if actionable else "watch",
        score=score,
        confidence=confidence,
        price=f.close,
        entry_low=_round(plan.entry_low),
        entry_high=_round(plan.entry_high),
        stop_loss=_round(plan.stop),
        targets=[_round(t) for t in plan.targets],
        risk_reward=round(plan.risk_reward, 2),
        holding_period=recipe.holding_period,
        max_sessions=recipe.max_sessions,
        supports=[_round(x) for x in levels.supports],
        resistances=[_round(x) for x in levels.resistances],
        reasons=reasons,
        factors=factors,
        risks=risks,
        invalidation=_invalidation(recipe, f, plan, d),
        inputs=f.inputs(),
        setups=[s for s in setups if s.direction == direction],
    )


def _extension(horizon: str, f: Features, d: int) -> str | None:
    """A risk line when price is stretched far from its trend average in the trade direction."""
    if horizon == "long_term" and finite(f.ema200) and f.ema200 > 0:
        gap = f.close / f.ema200 - 1.0
        if gap * d > 0.5:
            side = "above" if d > 0 else "below"
            return (
                f"Extended: {abs(gap) * 100:.0f}% {side} the 200-day EMA, prone to sharp pullbacks"
            )
    if horizon == "swing" and finite(f.atr14) and f.atr14 > 0:
        gap_atr = (f.close - f.ema50) / f.atr14
        if gap_atr * d > 5:
            side = "above" if d > 0 else "below"
            return f"Extended: {abs(gap_atr):.1f} ATR {side} the 50-day EMA, chasing risk"
    return None


def _round(x: float) -> float:
    return round(x, 2) if math.isfinite(x) else x


def _invalidation(recipe: Recipe, f: Features, plan: Plan, d: int) -> list[str]:
    side = "below" if d > 0 else "above"
    out = [f"Daily close {side} the stop-loss {plan.stop:.2f}"]
    if recipe.horizon == "next_session":
        word = "above" if d > 0 else "below"
        trigger = plan.entry_low if d > 0 else plan.entry_high
        out.insert(0, f"Price does not trade {word} {trigger:.2f} in the next session")
    elif recipe.horizon == "swing" and d > 0 and finite(f.dc20_high) and f.close > f.dc20_high:
        out.append(f"Close back below the breakout level {f.dc20_high:.2f}")
    elif recipe.horizon == "swing" and d < 0 and finite(f.dc20_low) and f.close < f.dc20_low:
        out.append(f"Close back above the breakdown level {f.dc20_low:.2f}")
    elif recipe.horizon == "long_term":
        out.append(f"Weekly close {side} the 200-day EMA {f.ema200:.2f}")
    out.append("NIFTY closes " + ("below" if d > 0 else "above") + " its 50-day EMA")
    return out


@dataclass(frozen=True)
class Scan:
    picks: list[Opportunity]
    setups: list[Setup]  # every swing setup at this bar, whether or not a pick was made
    features: Features
    rejections: dict[str, Rejection] = field(default_factory=dict)  # horizons with no pick


def scan(bars: pd.DataFrame, benchmark: pd.Series | None, regime: Regime) -> Scan | None:
    """Every horizon's pick and every swing setup for one listing at its last bar.

    None when history is too short. Shared by the daily job and the backtest, so both score
    exactly the same way. Setups are only looked for in stocks the swing recipe would trade
    (price and liquidity floors).
    """
    features = compute_features(bars, benchmark)
    if features is None:
        return None
    swing = RECIPES["swing"]
    setups: list[Setup] = []
    picks = []
    rejections: dict[str, Rejection] = {}
    for horizon, recipe in RECIPES.items():
        levels = find_levels(
            bars, k=recipe.pivot_k, lookback=recipe.pivot_lookback, atr=features.atr14
        )
        if recipe is swing and _tradeable(features, swing):
            setups = detect_setups(bars, features, levels)
        result = assess(horizon, features, levels, regime, setups if recipe is swing else ())
        if isinstance(result, Opportunity):
            picks.append(result)
        else:
            rejections[horizon] = result
    return Scan(picks, setups, features, rejections)


def _tradeable(f: Features, recipe: Recipe) -> bool:
    return f.close >= MIN_PRICE and f.traded_value_20 >= recipe.min_traded_value


def score_listing(
    bars: pd.DataFrame, benchmark: pd.Series | None, regime: Regime
) -> list[Opportunity] | None:
    """Every horizon's pick for one listing at its last bar; None when history is too short."""
    result = scan(bars, benchmark, regime)
    return None if result is None else result.picks
