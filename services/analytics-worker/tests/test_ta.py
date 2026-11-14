from pathlib import Path

import numpy as np
import pandas as pd
from analytics_worker.indicators.ta import TA_COLUMNS, compute_ta_frame
from analytics_worker.signals.high_volume_buy import evaluate_at_index

GOLDEN = Path(__file__).parent / "fixtures" / "ta_golden.csv"


def test_ta_columns_count():
    assert len(TA_COLUMNS) == 22


def test_ta_matches_vinzo_core():
    golden = pd.read_csv(GOLDEN, index_col="ts", parse_dates=["ts"])
    inputs = golden[["open", "high", "low", "close", "volume"]]
    out = compute_ta_frame(inputs)
    assert len(out) == 300
    for col in TA_COLUMNS:
        assert np.allclose(
            out[col].to_numpy(dtype=float),
            golden[col].to_numpy(dtype=float),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        ), col


def _frame(last_volume: int, n: int = 21) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC", name="ts")
    close = [100.0 + i * 0.1 for i in range(n)]
    open_ = [c - 0.05 for c in close]
    volume = [1000] * (n - 1) + [last_volume]
    return pd.DataFrame(
        {
            "open": open_,
            "high": [c + 1 for c in close],
            "low": [o - 1 for o in open_],
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def test_hvb_rule():
    hit = evaluate_at_index(_frame(2500), 20)
    assert hit is not None
    assert hit["strength"] == 2.5
    assert hit["rationale"].startswith("High volume buy: vol ")
    assert hit["meta"]["lookback"] == 20
    assert evaluate_at_index(_frame(1900), 20) is None
