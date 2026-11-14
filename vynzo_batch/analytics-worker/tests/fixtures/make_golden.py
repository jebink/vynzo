"""Regenerate ta_golden.csv from vinzo-core's compute_ta_frame.

Usage: python make_golden.py --vinzo-core PATH_TO/vinzo-core/market_data
"""

import argparse
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).with_name("ta_golden.csv")


def load_core_indicators(market_data_dir: Path):
    sys.path.insert(0, str(market_data_dir.resolve().parent))
    try:
        from market_data import indicators
    except Exception:
        for name in ("market_data.indicators", "market_data.db", "market_data.provider"):
            sys.modules.pop(name, None)
        for name in ("db", "provider"):
            sys.modules[f"market_data.{name}"] = types.ModuleType(f"market_data.{name}")
        from market_data import indicators
    return indicators


def build_input() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = 300
    close = 100 + np.cumsum(rng.normal(0, 1.5, n))
    close = np.maximum(close, 5.0)
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.5, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.5, n)
    volume = rng.integers(100_000, 1_000_000, n).astype("int64")
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC", name="ts")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vinzo-core", required=True, type=Path, help="vinzo-core market_data dir")
    args = parser.parse_args()
    indicators = load_core_indicators(args.vinzo_core)
    out = indicators.compute_ta_frame(build_input())
    cols = ["open", "high", "low", "close", "volume", *indicators.TA_COLUMNS]
    out[cols].to_csv(OUT, float_format="%.17g")
    print(f"wrote {len(out)} rows to {OUT}")


if __name__ == "__main__":
    main()
