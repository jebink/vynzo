"""Indicator values at the last daily bar, the inputs every opportunity recipe scores."""

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from analytics_worker.indicators.ta import (
    adx,
    atr,
    bollinger_width,
    donchian,
    ema,
    macd,
    obv,
    relative_volume,
    rsi,
)

MIN_BARS = 60  # enough for every short-horizon input; long-term needs LONG_TERM_MIN_BARS
LONG_TERM_MIN_BARS = 260
NAN = float("nan")
VOLUME_ANOMALY = 10.0  # relative volume above this is more likely a block deal or a data error


@dataclass(frozen=True)
class Features:
    """Values at the last bar. Any value may be NaN when history is too short for it."""

    as_of: pd.Timestamp
    bars: int
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    ema9: float
    ema21: float
    ema50: float
    ema200: float
    ema50_slope_10: float  # fractional change of the 50-EMA over 10 bars
    ema200_slope_20: float  # fractional change of the 200-EMA over 20 bars
    rsi14: float
    rsi14_prev: float
    macd_hist: float
    macd_hist_prev: float
    adx14: float
    plus_di: float
    minus_di: float
    atr14: float
    atr_pct: float  # ATR as % of close
    rvol20: float  # today's volume / previous 20-day average
    dc20_high: float  # highest high of the 20 bars before today
    dc20_low: float
    dc55_high: float
    dc55_low: float
    high_52w: float  # over the last 252 bars including today
    low_52w: float
    bb_width_pctile: float  # today's Bollinger width percentile over 120 bars, 0-100
    squeeze_release: bool  # width was in its lowest 20% within 5 bars and is expanding now
    obv_slope_20: float  # OBV change over 20 bars / 20-bar volume, about [-1, 1]
    obv_slope_60: float
    ret_5: float
    ret_20: float
    ret_63: float
    ret_126: float
    ret_252: float
    rs_20: float  # stock return minus NIFTY return over the same bars
    rs_63: float
    rs_126: float
    rs_252: float
    traded_value_20: float  # average close x volume over 20 bars, rupees
    gap_pct: float  # today's open vs previous close, %
    range_atr: float  # today's high-low range in ATRs
    close_location: float  # where the close sits in today's range, 0 (low) to 1 (high)

    def inputs(self) -> dict[str, float | None]:
        """JSON-safe snapshot of the scored values (NaN becomes None), for provenance."""
        out: dict[str, float | None] = {}
        for key, value in asdict(self).items():
            if key == "as_of":
                continue
            if isinstance(value, bool):
                out[key] = float(value)
            else:
                out[key] = None if not finite(value) else round(float(value), 6)
        return out


def finite(x: float | None) -> bool:
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def _last(series: pd.Series, back: int = 0) -> float:
    if len(series) <= back:
        return NAN
    value = series.iloc[-1 - back]
    return float(value) if pd.notna(value) else NAN


def _ret(close: pd.Series, n: int) -> float:
    if len(close) <= n:
        return NAN
    base = float(close.iloc[-1 - n])
    return float(close.iloc[-1]) / base - 1.0 if base > 0 else NAN


def _slope(series: pd.Series, n: int) -> float:
    now, then = _last(series), _last(series, n)
    return now / then - 1.0 if finite(now) and finite(then) and then != 0 else NAN


def _obv_slope(obv_line: pd.Series, volume: pd.Series, n: int) -> float:
    if len(obv_line) <= n:
        return NAN
    total = float(volume.iloc[-n:].sum())
    if total <= 0:
        return NAN
    return (float(obv_line.iloc[-1]) - float(obv_line.iloc[-1 - n])) / total


def compute_features(
    bars: pd.DataFrame, benchmark_close: pd.Series | None = None
) -> Features | None:
    """Features at the last bar of ``bars`` (open/high/low/close/volume, ascending ts index).

    ``benchmark_close`` (NIFTY) is aligned on dates up to the stock's last bar for relative
    strength. Returns None with fewer than MIN_BARS bars.
    """
    if len(bars) < MIN_BARS:
        return None
    close, volume = bars["close"], bars["volume"].astype(float)
    hist = macd(close)[2]
    adx_line, plus_di, minus_di = adx(bars)
    atr_line = atr(bars)
    dc20_high, dc20_low = donchian(bars, 20)
    dc55_high, dc55_low = donchian(bars, 55)
    width = bollinger_width(close)
    obv_line = obv(close, volume)

    pctile = NAN
    recent_width = width.iloc[-120:].dropna()
    if len(recent_width) >= 20:
        pctile = float((recent_width <= recent_width.iloc[-1]).mean() * 100)
    squeeze_release = False
    if len(recent_width) >= 25:
        ranks = recent_width.rank(pct=True)
        squeeze_release = bool(
            (ranks.iloc[-6:-1] <= 0.2).any() and recent_width.iloc[-1] > recent_width.iloc[-2]
        )

    rs = dict.fromkeys((20, 63, 126, 252), NAN)
    if benchmark_close is not None and not benchmark_close.empty:
        bench = benchmark_close[benchmark_close.index <= bars.index[-1]]
        for n in rs:
            stock, index = _ret(close, n), _ret(bench, n)
            if finite(stock) and finite(index):
                rs[n] = stock - index

    last = bars.iloc[-1]
    c, h, lo = float(last["close"]), float(last["high"]), float(last["low"])
    prev_close = float(close.iloc[-2])
    atr14 = _last(atr_line)
    window_252 = bars.iloc[-252:]

    return Features(
        as_of=pd.Timestamp(bars.index[-1]),
        bars=len(bars),
        open=float(last["open"]),
        high=h,
        low=lo,
        close=c,
        prev_close=prev_close,
        ema9=_last(ema(close, 9)),
        ema21=_last(ema(close, 21)),
        ema50=_last(ema(close, 50)),
        ema200=_last(ema(close, 200)) if len(bars) >= 200 else NAN,
        ema50_slope_10=_slope(ema(close, 50), 10),
        ema200_slope_20=_slope(ema(close, 200), 20) if len(bars) >= 220 else NAN,
        rsi14=_last(rsi(close)),
        rsi14_prev=_last(rsi(close), 1),
        macd_hist=_last(hist),
        macd_hist_prev=_last(hist, 1),
        adx14=_last(adx_line),
        plus_di=_last(plus_di),
        minus_di=_last(minus_di),
        atr14=atr14,
        atr_pct=atr14 / c * 100 if finite(atr14) and c > 0 else NAN,
        rvol20=_last(relative_volume(volume, 20)),
        dc20_high=_last(dc20_high),
        dc20_low=_last(dc20_low),
        dc55_high=_last(dc55_high),
        dc55_low=_last(dc55_low),
        high_52w=float(window_252["high"].max()),
        low_52w=float(window_252["low"].min()),
        bb_width_pctile=pctile,
        squeeze_release=squeeze_release,
        obv_slope_20=_obv_slope(obv_line, volume, 20),
        obv_slope_60=_obv_slope(obv_line, volume, 60),
        ret_5=_ret(close, 5),
        ret_20=_ret(close, 20),
        ret_63=_ret(close, 63),
        ret_126=_ret(close, 126),
        ret_252=_ret(close, 252),
        rs_20=rs[20],
        rs_63=rs[63],
        rs_126=rs[126],
        rs_252=rs[252],
        traded_value_20=float((close.iloc[-20:] * volume.iloc[-20:]).mean()),
        gap_pct=(float(last["open"]) / prev_close - 1.0) * 100 if prev_close > 0 else NAN,
        range_atr=(h - lo) / atr14 if finite(atr14) and atr14 > 0 else NAN,
        close_location=(c - lo) / (h - lo) if h > lo else 0.5,
    )


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(np.clip(x, lo, hi)) if finite(x) else 0.0
