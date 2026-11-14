import numpy as np
import pytest
from analytics_worker.forecasting.models import (
    MODELS,
    backtest_path,
    naive_drift,
)

H = 20


@pytest.mark.parametrize("name", sorted(MODELS))
def test_flat_series_stays_flat(name):
    closes = np.full(400, 100.0)
    assert np.allclose(MODELS[name](closes, H), 100.0, rtol=1e-6)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_steady_growth_keeps_growing(name):
    closes = 100 * np.exp(0.001 * np.arange(400))  # +0.1% a day
    pred = MODELS[name](closes, H)
    assert len(pred) == H and pred[0] > closes[-1] and pred[-1] > pred[0]
    linear = closes[-1] * np.exp(0.001 * H)
    if name == "holt":  # damped trend: grows, but less than the straight line
        assert closes[-1] < pred[-1] < linear
    else:
        assert pred[-1] == pytest.approx(linear, rel=0.01)


def test_drift_extends_log_trend_exactly():
    closes = 50 * np.exp(0.002 * np.arange(300))
    assert naive_drift(closes, 3) == pytest.approx(closes[-1] * np.exp(0.002 * np.arange(1, 4)))


def test_backtest_path_scores_a_perfect_model():
    closes = 100 * np.exp(0.001 * np.arange(400))
    path, m = backtest_path(naive_drift, closes, H, sessions=200)
    assert len(path) == 200 and np.allclose(path, closes[-200:])
    assert m["mape"] == pytest.approx(0.0, abs=1e-6) and m["hit_rate"] == 1.0 and m["n"] == 10


def test_backtest_path_only_uses_the_past():
    closes = np.r_[np.full(300, 100.0), np.full(100, 200.0)]  # jump at index 300
    path, _ = backtest_path(naive_drift, closes, H, sessions=200)
    # The segment starting at the jump was forecast from flat history: it can't know the jump.
    assert np.allclose(path[100:120], 100.0)
    assert np.all(np.isnan(backtest_path(naive_drift, closes[:30], H)[0]))


@pytest.mark.parametrize("name", sorted(MODELS))
def test_suspended_then_jump_stays_finite_and_bounded(name):
    closes = np.r_[np.full(500, 144.15), 143.85, 151.04]  # carried-forward prices, then a gap
    pred = MODELS[name](closes, H)
    assert np.isfinite(pred).all() and pred.max() < closes[-1] * 3
