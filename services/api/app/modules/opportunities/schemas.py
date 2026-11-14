"""Pydantic response models for opportunities (the public API contract)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Horizon = Literal["next_session", "swing", "long_term"]


class FactorScore(BaseModel):
    group: str
    score: float  # -1 bearish .. +1 bullish
    reason: str


class SetupTag(BaseModel):
    """A named swing strategy that agrees with the pick (analytics-worker strategies.py)."""

    key: str
    variant: str
    reason: str


class Regime(BaseModel):
    score: float
    label: str
    notes: list[str]


class OpportunityItem(BaseModel):
    id: int
    listing_id: int
    exchange: str
    symbol: str
    company_name: str | None
    horizon: Horizon
    as_of: datetime
    direction: Literal["BUY", "SELL"]
    status: Literal["actionable", "watch"]
    score: int
    confidence: Literal["high", "medium", "low"]
    price: float
    entry_low: float
    entry_high: float
    stop_loss: float
    targets: list[float]
    risk_reward: float
    holding_period: str
    supports: list[float]
    resistances: list[float]
    reasons: list[str]
    factors: list[FactorScore]
    risks: list[str]
    invalidation: list[str]
    setups: list[SetupTag]
    calc_version: str
    sector: str | None
    market_cap: float | None  # INR, shares outstanding x price
    cap_category: Literal["large", "mid", "small"] | None


class OpportunitiesResponse(BaseModel):
    as_of: datetime | None
    generated_at: datetime | None
    regime: Regime | None
    data_note: str
    horizons: dict[Horizon, list[OpportunityItem]]


class Outcome(BaseModel):
    status: Literal["target_hit", "stopped", "expired", "not_triggered"]
    entry_at: datetime | None
    entry_price: float | None
    exit_at: datetime | None
    exit_price: float | None
    return_pct: float | None
    sessions_held: int | None


class OpportunityDetail(OpportunityItem):
    regime: Regime
    inputs: dict
    outcome: Outcome | None


class ScoreBand(BaseModel):
    band: str
    triggered: int
    hit_rate: float | None
    avg_return_pct: float | None


class HorizonPerformance(BaseModel):
    picks: int
    open: int
    closed: dict[str, int]
    hit_rate: float | None  # target hits / triggered closed picks
    avg_return_pct: float | None  # over triggered closed picks
    by_score: list[ScoreBand]


class ClosedPick(BaseModel):
    id: int
    symbol: str
    exchange: str
    horizon: Horizon
    direction: Literal["BUY", "SELL"]
    score: int
    as_of: datetime
    status: str
    return_pct: float | None
    exit_at: datetime | None


class PerformanceResponse(BaseModel):
    status: Literal["actionable", "watch", "all"]
    horizons: dict[Horizon, HorizonPerformance]
    recent: list[ClosedPick]


# ---- Stock page: today's strategies per horizon ----


class StockSetup(BaseModel):
    """A named swing setup detected today, in either direction."""

    key: str
    variant: str
    direction: Literal["BUY", "SELL"]
    reason: str
    stop: float


class StockPick(BaseModel):
    direction: Literal["BUY", "SELL"]
    status: Literal["actionable", "watch"]
    score: int
    confidence: Literal["high", "medium", "low"]
    price: float
    entry_low: float
    entry_high: float
    stop_loss: float
    targets: list[float]
    risk_reward: float
    holding_period: str
    supports: list[float]
    resistances: list[float]
    reasons: list[str]
    factors: list[FactorScore]
    risks: list[str]
    invalidation: list[str]
    setups: list[StockSetup]


class Rejection(BaseModel):
    """The first gate a horizon failed; factors are empty when it failed before scoring."""

    reason: str
    factors: list[FactorScore]
    score: int | None = None


class StockHorizon(BaseModel):
    pick: StockPick | None
    rejection: Rejection | None


class StockStrategiesResponse(BaseModel):
    exchange: str
    symbol: str
    as_of: datetime | None
    regime: Regime | None
    horizons: dict[Horizon, StockHorizon]
    setups: list[StockSetup]
