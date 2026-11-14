"""HTTP layer for opportunities: request parsing and response shaping only. No business logic."""

from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_db
from app.modules.opportunities import service
from app.modules.opportunities.schemas import (
    OpportunitiesResponse,
    OpportunityDetail,
    PerformanceResponse,
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


@router.get("/{pick_id}", response_model=OpportunityDetail)
def opportunity_detail(pick_id: int, conn: Conn):
    try:
        return service.detail(conn, pick_id)
    except service.PickNotFound:
        raise HTTPException(status_code=404, detail="opportunity not found") from None
