"""HTTP layer for instruments: request parsing and response shaping only. No business logic here."""

from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.core.dependencies import get_db
from app.modules.instruments import service
from app.modules.instruments.schemas import (
    Listing,
    ListingDetail,
    SelectionPage,
    SelectionRow,
    SelectionUpdate,
)

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


# ---- Ingestion selection (admin) ----
# No auth yet (Phase 2): anyone who can reach the API can change the selection.


@router.get("/selection", response_model=SelectionPage)
def list_selection(
    conn: Annotated[psycopg.Connection, Depends(get_db)],
    q: str | None = None,
    status: Literal["all", "selected", "unselected"] = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """Every symbol with its NSE and BSE listing states for the daily pipeline."""
    return service.list_selection(conn, q=q, status=status, offset=offset, limit=limit)


@router.put("/selection/{exchange}/{symbol}", response_model=SelectionRow)
def set_selection(
    exchange: Annotated[str, Path(pattern=EXCHANGE_PATTERN)],
    symbol: str,
    body: SelectionUpdate,
    conn: Annotated[psycopg.Connection, Depends(get_db)],
):
    """Select or deselect one exchange listing of a symbol for the daily pipeline."""
    try:
        return service.set_selection(conn, exchange, symbol, selected=body.selected)
    except service.SymbolNotFound:
        raise HTTPException(status_code=404, detail="symbol not found") from None
    except service.CannotListOnExchange:
        raise HTTPException(
            status_code=409, detail=f"{symbol} has no company to list on {exchange.upper()}"
        ) from None
