"""HTTP layer for signals: request parsing and response shaping only. No business logic here."""

from datetime import date
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_db
from app.modules.signals import service
from app.modules.signals.schemas import Signal, SignalType, SwingSignal

router = APIRouter(prefix="/signals", tags=["signals"])

Conn = Annotated[psycopg.Connection, Depends(get_db)]
Exchange = Annotated[str | None, Query(pattern="(?i)^(NSE|BSE)$")]
Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("/types", response_model=list[SignalType])
def get_signal_types(conn: Conn):
    return service.signal_types(conn)


@router.get("", response_model=list[Signal])
def get_signals(
    conn: Conn,
    signal_type: str | None = None,
    exchange: Exchange = None,
    symbol: str | None = None,
    since: date | None = None,
    limit: Limit = 100,
):
    return service.signals(
        conn, signal_type=signal_type, exchange=exchange, symbol=symbol, since=since, limit=limit
    )


@router.get("/swing", response_model=list[SwingSignal])
def get_swing(conn: Conn, exchange: Exchange = None, symbol: str | None = None, limit: Limit = 100):
    return service.swing(conn, exchange=exchange, symbol=symbol, limit=limit)
