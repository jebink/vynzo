"""Yahoo Finance provider (ported from vinzo-core provider.fetch_ohlcv)."""

from collections.abc import Callable
from datetime import UTC, date, timedelta

import pandas as pd

from market_ingestion.providers.base import RawRecord
from market_ingestion.timeframes import EOD_TIMEFRAMES, TIMEFRAMES

_INTRADAY = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
_COLS = ("Open", "High", "Low", "Close", "Volume")


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df = df.copy()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def _default_download(ticker: str, **kwargs) -> pd.DataFrame:
    """yf.download with a same-ticker Ticker.history retry (yfinance imported lazily)."""
    import yfinance as yf

    raw = yf.download(ticker, **kwargs)
    if raw is None or raw.empty:
        hist_kwargs = {k: v for k, v in kwargs.items() if k not in ("progress", "threads")}
        hist_kwargs["auto_adjust"] = False
        raw = yf.Ticker(ticker).history(**hist_kwargs)
    return raw


def _py(v):
    """Plain Python scalar: float (NaN kept as float('nan'))."""
    return float(v)


class YahooProvider:
    name = "yahoo"

    def __init__(self, download: Callable[..., pd.DataFrame] | None = None) -> None:
        self._download = download or _default_download

    def fetch_bars(
        self, provider_symbol: str, timeframe: str, start: date | None, end: date
    ) -> list[RawRecord]:
        cfg = TIMEFRAMES[timeframe]
        if cfg.yahoo_interval is None:
            raise ValueError(f"{timeframe} is aggregation-only; cannot fetch from provider")

        if start is None:
            lookback = cfg.yahoo_lookback or timedelta(days=61)
            start_day = end - lookback
        else:
            start_day = start
        if cfg.yahoo_lookback is not None:
            earliest = end - cfg.yahoo_lookback
            if start_day < earliest:
                start_day = earliest
        exclusive_end = end + timedelta(days=1)

        intraday = cfg.yahoo_interval in _INTRADAY
        kwargs: dict = dict(
            interval=cfg.yahoo_interval, auto_adjust=False, progress=False, threads=False
        )
        if start is None:
            if cfg.yahoo_interval == "1m":
                kwargs["period"] = "7d"
            elif intraday:
                kwargs["period"] = "60d"
            else:
                kwargs["period"] = "max"
        else:
            kwargs["start"] = start_day.isoformat()
            kwargs["end"] = exclusive_end.isoformat()

        raw = self._download(provider_symbol, **kwargs)
        if raw is None or raw.empty:
            return []

        raw = _flatten_columns(raw)
        keep = [c for c in _COLS if c in raw.columns]
        df = raw[keep].copy()

        idx = pd.to_datetime(df.index)
        if timeframe in EOD_TIMEFRAMES:
            # Legacy daily bars live at 00:00 UTC of the IST trading date: key on that date.
            if idx.tz is not None:
                idx = idx.tz_convert("Asia/Kolkata")
            idx = pd.DatetimeIndex(idx.normalize().tz_localize(None)).tz_localize("UTC")
        else:
            idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
        df.index = idx

        if start is not None:
            start_ts = pd.Timestamp(start_day, tz="UTC")
            end_ts = pd.Timestamp(exclusive_end, tz="UTC")
            df = df[(df.index >= start_ts) & (df.index < end_ts)]

        records: list[RawRecord] = []
        for ts, row in df.iterrows():
            payload: dict = {}
            for c in keep:
                v = _py(row[c])
                payload[c] = int(v) if c == "Volume" and v == v else v
            records.append(
                RawRecord(
                    provider=self.name,
                    provider_symbol=provider_symbol,
                    timeframe=timeframe,
                    bar_ts=pd.Timestamp(ts).to_pydatetime().astimezone(UTC),
                    payload=payload,
                )
            )
        return records
