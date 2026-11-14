"""HTTP layer for opportunities: request parsing and response shaping only. No business logic."""

from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.dependencies import get_db
from app.modules.instruments.service import ListingNotFound
from app.modules.opportunities import service
from app.modules.opportunities.schemas import (
    OpportunitiesResponse,
    OpportunityDetail,
    PerformanceResponse,
    StockStrategiesResponse,
)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

Conn = Annotated[psycopg.Connection, Depends(get_db)]


@router.get("", response_model=OpportunitiesResponse)
def current_opportunities(conn: Conn):
    """The newest session's picks per horizon, actionable first, then by score."""
    return service.current(conn)


@router.get("/performance", response_model=PerformanceResponse)
def opportunity_performance(
    conn: Conn, status: Literal["actionable", "watch", "all"] = "actionable"
):
    """Track record of actionable (default), monitor-only or all picks per horizon."""
    return service.performance(conn, status)


@router.get("/stocks/{exchange}/{symbol}", response_model=StockStrategiesResponse)
def stock_strategies(exchange: str, symbol: str, conn: Conn):
    """One stock's pick, or the gate it failed, per horizon as of the last close."""
    try:
        return service.stock_strategies(conn, exchange.upper(), symbol.upper())
    except ListingNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None


@router.get("/stocks/{exchange}/{symbol}/backtest")
def stock_backtest(exchange: str, symbol: str, conn: Conn):
    """Walk-forward backtest of every strategy on this stock's full history, streamed as NDJSON:
    {"type": "start"}, then {"type": "progress", "trades": [...]} per chunk, then
    {"type": "done", "summary": {"<horizon>:<strategy>": {...}}}. Read-only; ~20 s uncached."""
    try:
        lines = service.stock_backtest(conn, exchange.upper(), symbol.upper())
    except ListingNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None
    return StreamingResponse(lines, media_type="application/x-ndjson")


@router.get("/{pick_id}", response_model=OpportunityDetail)
def opportunity_detail(pick_id: int, conn: Conn):
    try:
        return service.detail(conn, pick_id)
    except service.PickNotFound:
        raise HTTPException(status_code=404, detail="opportunity not found") from None
