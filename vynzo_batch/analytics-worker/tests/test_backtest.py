"""Walk-forward backtest: no look-ahead, outcome wiring, de-duplication and summary stats."""

import numpy as np
import pandas as pd
import pytest
from analytics_worker.opportunities.backtest import (
    BacktestPick,
    SetupTrade,
    backtest_listing,
    dedupe,
    summarize,
    summarize_setups,
)
from analytics_worker.opportunities.outcomes import Outcome
from analytics_worker.opportunities.regime import market_regime


def _bars(n=520, seed=4):
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + 0.0015 + rng.normal(0, 0.012, n))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    idx = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * 1.008,
            "low": np.minimum(opens, closes) * 0.992,
            "close": closes,
            "volume": rng.integers(800_000, 2_500_000, n).astype(float),
        },
        index=idx,
    )


def _run(bars, sessions):
    regimes = {s: market_regime(None) for s in sessions}
    return backtest_listing(7, "TEST", bars, None, regimes, sessions).picks


def test_picks_only_use_bars_up_to_their_session():
    bars = _bars()
    sessions = list(bars.index[300:420])
    picks = _run(bars, sessions)
    assert picks and all(p.as_of in sessions for p in picks)
    # Wreck everything after the last session: picks made up to it must not change.
    cut = sessions[-1]
    wrecked = bars.copy()
    wrecked.loc[wrecked.index > cut, ["open", "high", "low", "close"]] *= 0.3
    again = _run(wrecked, sessions)
    key = lambda p: (p.as_of, p.horizon, p.direction, p.score, p.status)  # noqa: E731
    assert [key(p) for p in picks] == [key(p) for p in again]


def test_outcomes_come_from_later_bars():
    bars = _bars()
    picks = _run(bars, list(bars.index[300:400]))
    closed = [p for p in picks if p.outcome is not None and p.outcome.exit_at is not None]
    assert closed
    for p in closed:
        assert p.outcome.exit_at > p.as_of


def _pick(
    day, direction="BUY", status="target_hit", ret=5.0, exit_day=None, score=80, horizon="swing"
):
    as_of = pd.Timestamp(f"2026-01-{day:02d}", tz="UTC")
    exit_at = pd.Timestamp(f"2026-01-{exit_day:02d}", tz="UTC") if exit_day else None
    outcome = None if status is None else Outcome(status, as_of, 100.0, exit_at, 100.0, ret, 3)
    return BacktestPick(
        1, "X", horizon, as_of, direction, "actionable", score, "medium", "bullish", outcome
    )


def test_dedupe_skips_repeats_of_a_still_open_pick():
    first = _pick(5, exit_day=9)
    repeat = _pick(6, exit_day=9)  # first still open on the 6th
    after = _pick(12, exit_day=15)  # first closed on the 9th: a new recommendation
    other_side = _pick(7, direction="SELL", exit_day=8)
    kept = dedupe([first, repeat, after, other_side])
    assert kept == [first, other_side, after]


def test_summarize_hit_rate_returns_and_bands():
    picks = [
        _pick(1, ret=10.0, exit_day=2, score=90),
        _pick(3, status="stopped", ret=-5.0, exit_day=4, score=72),
        _pick(5, status="expired", ret=1.0, exit_day=6, score=72),
        _pick(7, status="not_triggered", ret=None),
        _pick(9, status=None),  # still open at the end of the data
    ]
    rows = summarize(picks, split=pd.Timestamp("2027-01-01", tz="UTC"))
    row = next(r for r in rows if r["group"] == ("in_sample", "swing", "BUY", "actionable"))
    assert row["picks"] == 5 and row["entered"] == 3 and row["open"] == 1
    assert row["hit_rate"] == pytest.approx(1 / 3)
    assert row["avg_return_pct"] == pytest.approx(2.0)
    assert row["bands"]["85-100"]["entered"] == 1 and row["bands"]["70-84"]["entered"] == 2


def test_setup_trades_ignore_the_future_and_close_on_later_bars():
    bars = _bars()
    sessions = list(bars.index[300:420])
    regimes = {s: market_regime(None) for s in sessions}
    trades = backtest_listing(7, "TEST", bars, None, regimes, sessions).setup_trades
    assert trades and {t.key for t in trades} > {"macd_momentum"}
    wrecked = bars.copy()
    wrecked.loc[wrecked.index > sessions[-1], ["open", "high", "low", "close"]] *= 0.3
    again = backtest_listing(7, "TEST", wrecked, None, regimes, sessions).setup_trades
    key = lambda t: (t.as_of, t.key, t.variant, t.direction)  # noqa: E731
    assert [key(t) for t in trades] == [key(t) for t in again]
    for t in trades:
        if t.outcome is not None and t.outcome.exit_at is not None:
            assert t.outcome.exit_at > t.as_of


def _trade(day, exit_day, key="breakout", ret=4.0):
    as_of = pd.Timestamp(f"2026-01-{day:02d}", tz="UTC")
    exit_at = pd.Timestamp(f"2026-01-{exit_day:02d}", tz="UTC")
    outcome = Outcome("target_hit", as_of, 100.0, exit_at, 104.0, ret, 2)
    return SetupTrade(1, "X", key, "", as_of, "BUY", "neutral", outcome)


def test_setup_trades_dedupe_per_strategy_and_compare_with_nifty():
    first, repeat, other = _trade(5, 9), _trade(6, 9), _trade(6, 9, key="macd_momentum")
    kept = dedupe([first, repeat, other])
    assert kept == [first, other]
    nifty = pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-01-05", "2026-01-09"], utc=True))
    rows = summarize_setups(kept, split=pd.Timestamp("2027-01-01", tz="UTC"), benchmark=nifty)
    row = next(r for r in rows if r["group"] == ("in_sample", "breakout", "BUY"))
    assert row["entered"] == 1 and row["excess_vs_nifty_pct"] == pytest.approx(3.0)
