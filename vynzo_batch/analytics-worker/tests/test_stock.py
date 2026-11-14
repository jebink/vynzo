from types import SimpleNamespace

import numpy as np
import pandas as pd
from analytics_worker.opportunities import stock


def _bars(closes, volume):
    """OHLCV around a close path: open at the previous close, 1% wicks."""
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * 1.01,
            "low": np.minimum(opens, closes) * 0.99,
            "close": closes,
            "volume": volume,
        },
        index=idx,
    )


def _inputs(n=420):
    rng = np.random.default_rng(3)
    walk = 100 * np.cumprod(
        1 + 0.001 + 0.02 * np.sin(np.arange(n) / 9) * 0.1 + rng.normal(0, 0.015, n)
    )
    bars = _bars(walk, rng.integers(500_000, 3_000_000, n).astype(float))
    nifty = _bars(100 * np.cumprod(np.full(n, 1.0004)), 0.0)
    return stock.StockInputs(1, "TEST", bars, {"NIFTY": nifty, "BANKNIFTY": None, "INDIAVIX": None})


def _trades(events):
    return sorted(
        (t["strategy"], t["as_of"], t["direction"], t["outcome"])
        for e in events
        if e["type"] == "progress"
        for t in e["trades"]
    )


def test_chunked_stream_matches_a_single_pass():
    inputs = _inputs()
    chunked = list(stock.backtest_events(inputs, chunk=37))
    single = list(stock.backtest_events(inputs, chunk=10**6))
    assert chunked[0]["type"] == "start" and chunked[-1]["type"] == "done"
    assert chunked[-2]["done"] == chunked[0]["sessions"]
    assert _trades(chunked) and _trades(chunked) == _trades(single)
    assert chunked[-1]["summary"].keys() == single[-1]["summary"].keys()


def test_current_reports_a_pick_or_a_reason_for_every_horizon():
    result = stock.current(_inputs())
    assert set(result["horizons"]) == {"next_session", "swing", "long_term"}
    for h in result["horizons"].values():
        assert (h["pick"] is None) != (h["rejection"] is None)


def _trade(ret, day):
    outcome = SimpleNamespace(
        status="target_hit", return_pct=ret, exit_at=pd.Timestamp(day), sessions_held=3
    )
    return SimpleNamespace(outcome=outcome)


def test_equity_curve_compounds_and_measures_drawdown():
    curve, dd = stock.equity_curve(
        [_trade(-50, "2024-01-03"), _trade(10, "2024-01-01"), _trade(100, "2024-01-05")]
    )
    assert [round(p["equity"], 3) for p in curve] == [1.1, 0.55, 1.1]
    assert round(dd, 6) == 50.0
    assert stock.equity_curve([]) == ([], None)
