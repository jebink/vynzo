"""HTTP layer for fundamentals: request parsing and response shaping only. No
business logic here.
"""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_db
from app.modules.fundamentals import service
from app.modules.fundamentals.schemas import CompanyOverview, CorporateEvent

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])

Conn = Annotated[psycopg.Connection, Depends(get_db)]
IST = ZoneInfo("Asia/Kolkata")


@router.get("/events", response_model=list[CorporateEvent])
def get_events(
    conn: Conn,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    """Upcoming corporate events (results, ex-dividend) from today (IST) for `days` days."""
    return service.upcoming_events(conn, today=datetime.now(IST).date(), days=days, limit=limit)


@router.get("/{exchange}/{symbol}", response_model=CompanyOverview)
def company_overview(exchange: str, symbol: str, conn: Conn):
    """Current condition of the company: valuation, growth, debt, ownership, dividends, orders."""
    try:
        return service.company_overview(
            conn, exchange.upper(), symbol.upper(), datetime.now(IST).date()
        )
    except service.CompanyNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None
