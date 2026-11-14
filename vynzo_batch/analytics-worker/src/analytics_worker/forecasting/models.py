"""Daily close forecasters and their walk-forward scorer. Pure numpy: no I/O.

Every model maps a history of closes (oldest first) to the next `horizon` closes;
`backtest_path` replays them over past sessions. They work on
log prices, so a forecast can never go negative.
"""

from collections.abc import Callable

import numpy as np

Model = Callable[[np.ndarray, int], np.ndarray]

DRIFT_WINDOW = 250  # sessions of returns behind the drift estimate (~1 trading year)
LAGS = 5
RIDGE_WINDOW = 500
RIDGE_ALPHA = 1.0


def naive_drift(closes: np.ndarray, horizon: int) -> np.ndarray:
    """Last close extended by the mean daily log return: the baseline the others must beat."""
    logs = np.log(closes[-(DRIFT_WINDOW + 1) :])
    drift = np.diff(logs).mean() if len(logs) > 1 else 0.0
    return np.exp(logs[-1] + drift * np.arange(1, horizon + 1))


def _holt_sse(y: np.ndarray, alpha: float, beta: float, phi: float) -> tuple[float, float, float]:
    level, trend, sse = y[0], y[1] - y[0], 0.0
    for v in y[1:]:
        pred = level + phi * trend
        sse += (v - pred) ** 2
        new_level = alpha * v + (1 - alpha) * pred
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return sse, level, trend


def holt_damped(closes: np.ndarray, horizon: int) -> np.ndarray:
    """Holt's linear trend on log prices with a damped trend (phi), fitted by a small grid."""
    y = np.log(closes[-DRIFT_WINDOW:])
    if len(y) < 3:
        return np.full(horizon, closes[-1])
    phi = 0.9  # damping: an undamped trend runs away over a 20-day horizon
    best = min(
        (_holt_sse(y, a, b, phi) for a in (0.2, 0.4, 0.6, 0.8, 0.95) for b in (0.01, 0.05, 0.15)),
        key=lambda r: r[0],
    )
    _, level, trend = best
    damp = np.cumsum(phi ** np.arange(1, horizon + 1))
    return np.exp(level + damp * trend)


def _features(r: np.ndarray, t: int) -> np.ndarray:
    """At return index t: the last LAGS returns and the 20-session momentum."""
    return np.concatenate([r[t - LAGS + 1 : t + 1][::-1], [r[max(0, t - 19) : t + 1].sum()]])


def ridge_returns(closes: np.ndarray, horizon: int) -> np.ndarray:
    """Ridge regression of the next log return on lagged returns, rolled forward recursively."""
    r = np.diff(np.log(closes[-(RIDGE_WINDOW + 1) :]))
    rows = range(LAGS - 1, len(r) - 1)
    if len(rows) < 50:
        return naive_drift(closes, horizon)
    x = np.array([_features(r, t) for t in rows])
    y = r[LAGS:]
    mu, sd = x.mean(0), x.std(0) + 1e-12
    xs = (x - mu) / sd
    coef = np.linalg.solve(xs.T @ xs + RIDGE_ALPHA * np.eye(xs.shape[1]), xs.T @ (y - y.mean()))
    cap = np.abs(r).max()
    path, last = list(r), np.log(closes[-1])
    out = []
    for _ in range(horizon):
        step = y.mean() + ((_features(np.array(path), len(path) - 1) - mu) / sd) @ coef
        # Near-constant history (e.g. a suspended stock) makes the fit unstable: never step
        # further than the biggest daily move it was trained on.
        step = float(np.clip(step, -cap, cap))
        path.append(step)
        last += step
        out.append(last)
    return np.exp(np.array(out))


MODELS: dict[str, Model] = {
    "drift": naive_drift,
    "holt": holt_damped,
    "ridge": ridge_returns,
}


def backtest_path(
    model: Model, closes: np.ndarray, horizon: int, sessions: int = 500
) -> tuple[np.ndarray, dict[str, float | int] | None]:
    """What `model` would have predicted over the last `sessions` closes, and how wrong it was.

    Forecasts are made every `horizon` sessions from data up to that day only, each covering the
    next `horizon` sessions, and stitched into one line aligned to `closes[-sessions:]` (NaN where
    there was too little history). Metrics: MAPE (%) over every point, and the share of segments
    whose end-of-segment direction was right.
    """
    sessions = min(sessions, len(closes))
    first = len(closes) - sessions
    path = np.full(sessions, np.nan)
    errors, hits, n = [], 0, 0
    for o in range(first, len(closes), horizon):
        if o < 60:
            continue
        actual = closes[o : o + horizon]
        pred = model(closes[:o], horizon)[: len(actual)]
        path[o - first : o - first + len(actual)] = pred
        errors.append(np.abs(pred - actual) / actual)
        if len(actual) == horizon:
            base = closes[o - 1]
            hits += int(np.sign(pred[-1] - base) == np.sign(actual[-1] - base))
            n += 1
    if not n:
        return path, None
    mape = float(np.mean(np.concatenate(errors))) * 100
    return path, {"mape": round(mape, 2), "hit_rate": round(hits / n, 2), "n": n}
