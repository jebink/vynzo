"""Opportunity engine on synthetic daily bars."""

import numpy as np
import pandas as pd
import pytest
from analytics_worker.opportunities.engine import (
    CALC_VERSION,
    MIN_CONFLUENCE,
    RECIPES,
    Factor,
    confluence,
    evaluate,
)
from analytics_worker.opportunities.features import compute_features
from analytics_worker.opportunities.levels import find_levels
from analytics_worker.opportunities.outcomes import evaluate_outcome
from analytics_worker.opportunities.regime import Regime, market_regime


def _bars(closes, *, volume=1_000_000, last_volume=None, wick=0.006, seed=0):
    """OHLCV around a close path: open at the previous close, small wicks."""
    closes = np.asarray(closes, dtype=float)
    rng = np.random.default_rng(seed)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    spread = closes * wick * (1 + rng.random(len(closes)))
    highs = np.maximum(opens, closes) + spread
    lows = np.minimum(opens, closes) - spread
    vols = np.full(len(closes), float(volume))
    if last_volume is not None:
        vols[-1] = last_volume
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx
    )


def _uptrend_breakout(n=320, seed=1):
    """Steady uptrend, a 25-session flag, then a wide-range breakout on 3x volume."""
    rng = np.random.default_rng(seed)
    trend = 100 * np.cumprod(1 + 0.0025 + rng.normal(0, 0.006, n - 26))
    top = trend[-1]
    flag = top * (1 - 0.02 * np.abs(np.sin(np.arange(25) / 3)))
    closes = np.concatenate([trend, flag, [top * 1.04]])
    bars = _bars(closes, seed=seed)
    bars.iloc[-1, bars.columns.get_loc("volume")] = 3_000_000
    bars.iloc[-1, bars.columns.get_loc("open")] = top * 0.995
    bars.iloc[-1, bars.columns.get_loc("high")] = top * 1.042
    bars.iloc[-1, bars.columns.get_loc("low")] = top * 0.99
    return bars


def _mirror(bars):
    """Price-mirrored bars (a downtrend breakdown from an uptrend breakout)."""
    pivot = 2 * float(bars["close"].iloc[0])
    out = bars.copy()
    out["open"], out["close"] = pivot - bars["open"], pivot - bars["close"]
    out["high"], out["low"] = pivot - bars["low"], pivot - bars["high"]
    return out


def _benchmark(n=320):
    return _bars(100 * np.cumprod(np.full(n, 1.0004)))["close"]


NEUTRAL = market_regime(None)


def _evaluate(horizon, bars, regime=NEUTRAL):
    f = compute_features(bars, _benchmark(len(bars)))
    recipe = RECIPES[horizon]
    levels = find_levels(bars, k=recipe.pivot_k, lookback=recipe.pivot_lookback, atr=f.atr14)
    return evaluate(horizon, f, levels, regime)


def test_swing_breakout_is_an_actionable_buy_with_a_consistent_plan():
    opp = _evaluate("swing", _uptrend_breakout())
    assert opp is not None
    assert opp.direction == "BUY" and opp.status == "actionable"
    assert opp.score >= 70 and opp.confidence in ("medium", "high")
    assert opp.stop_loss < opp.entry_low <= opp.price <= opp.entry_high
    assert opp.entry_high < opp.targets[0] < opp.targets[1]
    entry = (opp.entry_low + opp.entry_high) / 2
    assert opp.risk_reward == pytest.approx(
        (opp.targets[0] - entry) / (entry - opp.stop_loss), abs=0.01
    )
    assert any("Breakout above the 20-day high" in r for r in opp.reasons)
    assert opp.max_sessions == 20 and opp.holding_period == "5–20 trading sessions"
    assert opp.inputs["close"] == pytest.approx(opp.price)


def test_mirrored_breakdown_is_a_sell_with_the_stop_above():
    opp = _evaluate("swing", _mirror(_uptrend_breakout()))
    assert opp is not None and opp.direction == "SELL"
    assert opp.stop_loss > opp.entry_high >= opp.price >= opp.entry_low
    assert opp.targets[0] < opp.entry_low and opp.targets[1] < opp.targets[0]


def test_choppy_market_gives_no_opportunity():
    rng = np.random.default_rng(7)
    closes = 100 + 2 * np.sin(np.arange(320) / 4) + rng.normal(0, 0.3, 320)
    bars = _bars(closes)
    for horizon in RECIPES:
        assert _evaluate(horizon, bars) is None, horizon


def test_long_term_confidence_is_capped_at_medium():
    opp = _evaluate("long_term", _uptrend_breakout())
    assert opp is not None and opp.direction == "BUY"
    assert opp.confidence in ("medium", "low")
    assert any("Fundamentals not yet included" in r for r in opp.risks)


def test_next_session_triggers_beyond_todays_high():
    bars = _uptrend_breakout()
    opp = _evaluate("next_session", bars)
    assert opp is not None and opp.direction == "BUY"
    assert opp.status == "watch"  # monitor-only until intraday data exists
    assert opp.entry_low == pytest.approx(round(float(bars["high"].iloc[-1]), 2))
    assert opp.max_sessions == 1
    assert opp.invalidation[0].startswith("Price does not trade above")


def test_illiquid_and_penny_stocks_are_excluded():
    bars = _uptrend_breakout()
    thin = bars.assign(volume=bars["volume"] / 1000)
    assert _evaluate("swing", thin) is None
    penny = bars.assign(**{c: bars[c] / 10 for c in ("open", "high", "low", "close")})
    assert _evaluate("swing", penny) is None


def test_opposing_market_regime_lowers_the_score():
    bars = _uptrend_breakout()
    neutral = _evaluate("swing", bars)
    falling_market = market_regime(_mirror(_bars(100 * np.cumprod(np.full(320, 1.003)))))
    assert falling_market.label == "bearish"
    against = _evaluate("swing", bars, falling_market)
    assert against is None or against.score < neutral.score
    if against is not None:
        assert any("against this BUY" in r for r in against.risks)


def test_confluence_needs_several_agreeing_groups():
    weights = RECIPES["swing"].weights
    one_strong = [
        Factor("price_action", 1.0, "x"),
        Factor("trend", 0.0, "y"),
        Factor("momentum", 0.1, "z"),
    ]
    c = confluence(weights, one_strong)
    assert c.direction == 1 and len(c.agreeing) < MIN_CONFLUENCE
    many = [Factor(g, 0.6, g) for g in ("trend", "momentum", "price_action")] + [
        Factor("volume", -0.5, "v")
    ]
    c = confluence(weights, many)
    assert len(c.agreeing) == 3 and [x.group for x in c.conflicting] == ["volume"]


def test_levels_merge_nearby_pivots_and_split_by_close():
    bars = _uptrend_breakout()
    f = compute_features(bars)
    levels = find_levels(bars, k=5, lookback=120, atr=f.atr14)
    assert all(x < f.close for x in levels.supports)
    assert all(x > f.close for x in levels.resistances)
    assert levels.supports == sorted(levels.supports, reverse=True)


def test_calc_version_is_set():
    assert CALC_VERSION.startswith("opp-")


# ---- Outcomes ----


def _future(rows):
    idx = pd.date_range("2026-01-02", periods=len(rows), freq="B", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


PICK = {
    "direction": "BUY",
    "entry_low": 99.0,
    "entry_high": 101.0,
    "stop_loss": 95.0,
    "targets": [110.0, 115.0],
    "max_sessions": 5,
    "horizon": "swing",
}


def test_outcome_target_hit():
    out = evaluate_outcome(PICK, _future([(100, 102, 99, 101), (101, 111, 100, 109)]))
    assert out.status == "target_hit" and out.exit_price == 110.0
    assert out.entry_price == 100.0 and out.sessions_held == 2
    assert out.return_pct == pytest.approx(10.0)


def test_outcome_stop_wins_a_bar_that_touches_both():
    out = evaluate_outcome(PICK, _future([(100, 112, 94, 100)]))
    assert out.status == "stopped" and out.exit_price == 95.0
    assert out.return_pct == pytest.approx(-5.0)


def test_outcome_open_expired_and_not_triggered():
    assert evaluate_outcome(PICK, _future([(100, 103, 99, 102)])) is None  # still open
    out = evaluate_outcome(PICK, _future([(100, 103, 99, 102)] * 5))
    assert out.status == "expired" and out.exit_price == 102.0
    gapped = [(105, 107, 104, 106)] * 3  # never back in the entry range within 3 sessions
    assert evaluate_outcome(PICK, _future(gapped)).status == "not_triggered"


def test_outcome_sell_direction():
    sell = {**PICK, "direction": "SELL", "stop_loss": 105.0, "targets": [90.0, 85.0]}
    out = evaluate_outcome(sell, _future([(100, 101, 89, 90)]))
    assert out.status == "target_hit" and out.return_pct == pytest.approx(10.0)


def test_extreme_volume_counts_weakly_and_is_flagged():
    bars = _uptrend_breakout()
    bars.iloc[-1, bars.columns.get_loc("volume")] = 150_000_000  # 150x: block deal or bad data
    f = compute_features(bars, _benchmark(len(bars)))
    volume = next(x for x in RECIPES["swing"].factors(f) if x.group == "volume")
    assert volume.score <= 0.75 and "block deal or a data error" in volume.reason
    opp = _evaluate("swing", bars)
    assert opp is not None and any("150× normal" in r for r in opp.risks)


def test_parabolic_long_term_move_is_penalised_as_extended():
    rng = np.random.default_rng(3)
    calm = 100 * np.cumprod(1 + 0.0008 + rng.normal(0, 0.005, 300))
    parabolic = calm[-1] * np.cumprod(np.full(60, 1.012))  # about +100% in 60 sessions
    opp = _evaluate("long_term", _bars(np.concatenate([calm, parabolic])))
    assert opp is None or (
        opp.status == "watch" and any(r.startswith("Extended:") for r in opp.risks)
    )


def test_a_market_turning_against_the_trade_blocks_actionable():
    bars = _uptrend_breakout()
    # A long uptrend whose last 15 sessions fall hard: slow trend up, short-term down.
    up = 100 * np.cumprod(np.full(305, 1.002))
    nifty = _bars(np.concatenate([up, up[-1] * np.cumprod(np.full(15, 0.992))]))
    regime = market_regime(nifty)
    assert regime.short_term < -0.25
    opp = _evaluate("swing", bars, regime)
    assert opp is None or opp.status == "watch"
    if opp is not None:
        assert any("short-term direction is against this BUY" in r for r in opp.risks)


# Backtest-driven rules (opp-1.4.0): see docs/superpowers/plans/2026-11-14-market-opportunities.md.
BEARISH_CALM = Regime(score=-0.4, label="bearish", notes=["test"], short_term=0.0)
BULLISH_CALM = Regime(score=0.4, label="bullish", notes=["test"], short_term=0.0)


def test_sell_picks_are_monitor_only_even_in_a_falling_market():
    for horizon in ("swing", "long_term"):
        opp = _evaluate(horizon, _mirror(_uptrend_breakout()), BEARISH_CALM)
        if opp is None:
            continue
        assert opp.direction == "SELL" and opp.status == "watch", horizon
        assert any(r.startswith("Monitor only: SELL") for r in opp.risks), horizon


def test_a_bearish_market_blocks_an_actionable_buy():
    bars = _uptrend_breakout()
    assert _evaluate("swing", bars, BULLISH_CALM).status == "actionable"
    opp = _evaluate("swing", bars, BEARISH_CALM)
    assert opp is None or opp.status == "watch"
    if opp is not None:
        assert any("against this BUY" in r for r in opp.risks)
