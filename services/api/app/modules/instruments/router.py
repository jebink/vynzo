"""HTTP layer for instruments: request parsing and response shaping only. No business logic here."""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.dependencies import get_db
from app.modules.instruments import service
from app.modules.instruments.schemas import Listing, ListingDetail

router = APIRouter(prefix="/instruments", tags=["instruments"])

EXCHANGE_PATTERN = "(?i)^(NSE|BSE)$"


@router.get("/listings", response_model=list[Listing])
def search_listings(
    conn: Annotated[psycopg.Connection, Depends(get_db)],
    q: str | None = None,
    exchange: Annotated[str | None, Query(pattern=EXCHANGE_PATTERN)] = None,
    active: bool = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.search(conn, q=q, exchange=exchange, active=active, limit=limit)


@router.get("/listings/{exchange}/{symbol}", response_model=ListingDetail)
def get_listing(exchange: str, symbol: str, conn: Annotated[psycopg.Connection, Depends(get_db)]):
    try:
        return service.listing_detail(conn, exchange, symbol)
    except service.ListingNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None
