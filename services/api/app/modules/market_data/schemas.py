"""Pydantic request/response models for market_data (the public API contract)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

Timeframe = Literal["1d", "1w", "1mo", "75m", "15m", "5m", "1m"]


class Bar(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class BarsResponse(BaseModel):
    listing_id: int
    exchange: str
    symbol: str
    timeframe: Timeframe
    bars: list[Bar]


class IndicatorRow(BaseModel):
    ts: datetime
    calc_version: str
    rsi_14: float | None
    ema_9: float | None
    ema_21: float | None
    ema_50: float | None
    ema_200: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    atr_14: float | None
    vwap: float | None
    adx_14: float | None
    plus_di_14: float | None
    minus_di_14: float | None
    rvol_20: float | None
    donchian_high_20: float | None
    donchian_low_20: float | None
    donchian_high_55: float | None
    bb_width: float | None
    obv: float | None
    ema200_slope_20: float | None
    extension_atr: float | None
    ret_126: float | None


class IndicatorsResponse(BaseModel):
    listing_id: int
    exchange: str
    symbol: str
    rows: list[IndicatorRow]


class StockSnapshot(BaseModel):
    """One ingested listing's latest daily close, its change and recent closes for a sparkline."""

    listing_id: int
    exchange: str
    symbol: str
    kind: str
    company_name: str | None
    is_active: bool
    latest_ts: datetime | None
    close: float | None
    previous_close: float | None
    change_pct: float | None
    volume: int | None
    closes: list[float]
    sector: str | None
    market_cap: float | None  # INR, shares outstanding x last close
    cap_category: Literal["large", "mid", "small"] | None


class OverviewResponse(BaseModel):
    as_of: datetime | None
    points: int
    stocks: list[StockSnapshot]


class ForecastPoint(BaseModel):
    date: date
    close: float


class ForecastMetrics(BaseModel):
    mape: float | None = None  # mean absolute % error of walk-forward forecasts
    hit_rate: float | None = None  # share of forecasts that got the 20-day direction right
    n: int | None = None  # forecasts scored


class ModelForecast(BaseModel):
    model: str
    as_of: date
    horizon: int
    history: list[ForecastPoint]  # what the model would have predicted over past sessions
    projection: list[ForecastPoint]  # sessions after the last bar
    metrics: ForecastMetrics


class ForecastResponse(BaseModel):
    listing_id: int
    exchange: str
    symbol: str
    best_model: str | None
    forecasts: list[ModelForecast]
