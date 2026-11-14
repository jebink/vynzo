"""Timeframe catalogue (ported from vinzo-core config.INTERVALS)."""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Timeframe:
    key: str
    table: str
    yahoo_interval: str | None  # None = derived by aggregation only
    overlap: timedelta | None  # re-fetch window for incremental EOD runs
    yahoo_lookback: timedelta | None = None  # max history Yahoo allows


_LONG = timedelta(days=365 * 30)

TIMEFRAMES: dict[str, Timeframe] = {
    "1m": Timeframe("1m", "ohlcv_1m", "1m", None, timedelta(days=7)),
    "5m": Timeframe("5m", "ohlcv_5m", "5m", None, timedelta(days=60)),
    "15m": Timeframe("15m", "ohlcv_15m", "15m", None, timedelta(days=60)),
    "75m": Timeframe("75m", "ohlcv_75m", None, None, None),
    "1d": Timeframe("1d", "ohlcv_1d", "1d", timedelta(days=7), _LONG),
    "1w": Timeframe("1w", "ohlcv_1w", "1wk", timedelta(days=21), _LONG),
    "1mo": Timeframe("1mo", "ohlcv_1mo", "1mo", timedelta(days=45), _LONG),
}

EOD_TIMEFRAMES = ("1d", "1w", "1mo")
