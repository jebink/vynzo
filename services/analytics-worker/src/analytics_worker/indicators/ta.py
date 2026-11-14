"""Technical analysis: verbatim port of vinzo-core indicators (core + swing-v2 factors).

Do not tidy the math: parity with the legacy ta_daily values depends on these exact
function bodies and ewm/rolling parameters. compute_ta_frame also computes ema_20, ret_63 and
ret_252, which TA_COLUMNS does not store.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Wilder ADX / +DI / -DI."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = atr(df, period)  # noqa: F841  # already Wilder-ish via ewm alpha; use true TR smooth below

    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_w = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_dm_s = (
        pd.Series(plus_dm, index=df.index)
        .ewm(alpha=1 / period, min_periods=period, adjust=False)
        .mean()
    )
    minus_dm_s = (
        pd.Series(minus_dm, index=df.index)
        .ewm(alpha=1 / period, min_periods=period, adjust=False)
        .mean()
    )

    plus_di = 100 * (plus_dm_s / atr_w.replace(0, np.nan))
    minus_di = 100 * (minus_dm_s / atr_w.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_line = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx_line, plus_di, minus_di


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol = df["volume"].cumsum().replace(0, np.nan)
    return (typical * df["volume"]).cumsum() / cum_vol


def relative_volume(volume: pd.Series, lookback: int = 20) -> pd.Series:
    avg = volume.shift(1).rolling(lookback, min_periods=lookback).mean()
    return volume / avg.replace(0, np.nan)


def donchian(df: pd.DataFrame, window: int) -> tuple[pd.Series, pd.Series]:
    # Prior window excludes current bar for breakout tests
    high = df["high"].shift(1).rolling(window, min_periods=window).max()
    low = df["low"].shift(1).rolling(window, min_periods=window).min()
    return high, low


def bollinger_width(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    mid = sma(close, window)
    std = close.rolling(window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return (upper - lower) / mid.replace(0, np.nan)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


def volume_profile(df: pd.DataFrame, bins: int = 24) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["price_level", "volume"])
    prices = (df["high"] + df["low"] + df["close"]) / 3.0
    cats = pd.cut(prices, bins=bins)
    grouped = df.groupby(cats, observed=False)["volume"].sum()
    out = grouped.reset_index()
    out.columns = ["price_level", "volume"]
    return out


def compute_ta_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["rsi_14"] = rsi(out["close"], 14)
    out["ema_9"] = ema(out["close"], 9)
    out["ema_21"] = ema(out["close"], 21)
    out["ema_20"] = ema(out["close"], 20)
    out["ema_50"] = ema(out["close"], 50)
    out["ema_200"] = ema(out["close"], 200)
    macd_line, macd_sig, macd_hist = macd(out["close"])
    out["macd"] = macd_line
    out["macd_signal"] = macd_sig
    out["macd_hist"] = macd_hist
    out["atr_14"] = atr(out, 14)
    out["vwap"] = vwap(out)

    adx_line, plus_di, minus_di = adx(out, 14)
    out["adx_14"] = adx_line
    out["plus_di_14"] = plus_di
    out["minus_di_14"] = minus_di
    out["rvol_20"] = relative_volume(out["volume"], 20)
    dh20, dl20 = donchian(out, 20)
    dh55, _ = donchian(out, 55)
    out["donchian_high_20"] = dh20
    out["donchian_low_20"] = dl20
    out["donchian_high_55"] = dh55
    out["bb_width"] = bollinger_width(out["close"], 20)
    out["obv"] = obv(out["close"], out["volume"])
    out["ema200_slope_20"] = out["ema_200"] - out["ema_200"].shift(20)
    out["extension_atr"] = (out["close"] - out["ema_50"]) / out["atr_14"].replace(0, np.nan)
    out["ret_63"] = out["close"] / out["close"].shift(63) - 1.0
    out["ret_126"] = out["close"] / out["close"].shift(126) - 1.0
    out["ret_252"] = out["close"] / out["close"].shift(252) - 1.0
    return out


TA_COLUMNS = (
    "rsi_14",
    "ema_9",
    "ema_21",
    "ema_50",
    "ema_200",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "vwap",
    "adx_14",
    "plus_di_14",
    "minus_di_14",
    "rvol_20",
    "donchian_high_20",
    "donchian_low_20",
    "donchian_high_55",
    "bb_width",
    "obv",
    "ema200_slope_20",
    "extension_atr",
    "ret_126",
)
