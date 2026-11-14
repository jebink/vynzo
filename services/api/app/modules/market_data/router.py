"""HTTP layer for market_data: request parsing and response shaping only. No business logic here."""

from datetime import date
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_db
from app.modules.instruments.service import ListingNotFound
from app.modules.market_data import service
from app.modules.market_data.schemas import (
    BarsResponse,
    ForecastResponse,
    IndicatorsResponse,
    OverviewResponse,
    Timeframe,
)

router = APIRouter(prefix="/market-data", tags=["market-data"])

Conn = Annotated[psycopg.Connection, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=5000)]

EXCHANGE_PATTERN = "(?i)^(NSE|BSE)$"


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="listing not found")


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    conn: Conn,
    exchange: Annotated[str | None, Query(pattern=EXCHANGE_PATTERN)] = None,
    points: Annotated[int, Query(ge=2, le=250)] = 60,
):
    """Every ingested stock with its latest daily close, change and last `points` closes."""
    return service.get_overview(conn, exchange=exchange, points=points)


@router.get("/{exchange}/{symbol}/bars", response_model=BarsResponse)
def get_bars(
    exchange: str,
    symbol: str,
    conn: Conn,
    timeframe: Timeframe = "1d",
    limit: Limit = 500,
    end: date | None = None,
):
    try:
        return service.get_bars(conn, exchange, symbol, timeframe=timeframe, limit=limit, end=end)
    except ListingNotFound:
        raise _not_found() from None


@router.get("/{exchange}/{symbol}/indicators", response_model=IndicatorsResponse)
def get_indicators(
    exchange: str, symbol: str, conn: Conn, limit: Limit = 500, end: date | None = None
):
    try:
        return service.get_indicators(conn, exchange, symbol, limit=limit, end=end)
    except ListingNotFound:
        raise _not_found() from None


@router.get("/{exchange}/{symbol}/forecast", response_model=ForecastResponse)
def get_forecast(exchange: str, symbol: str, conn: Conn):
    """What each model would have predicted over past sessions, scored by its error."""
    try:
        return service.get_forecast(conn, exchange, symbol)
    except ListingNotFound:
        raise _not_found() from None
