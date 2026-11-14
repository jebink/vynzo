"""HTTP layer for the focus module: request parsing and response shaping only."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends

from app.core.dependencies import get_db
from app.modules.focus import service
from app.modules.focus.schemas import FocusResponse

router = APIRouter(prefix="/focus", tags=["focus"])
IST = ZoneInfo("Asia/Kolkata")


@router.get("", response_model=FocusResponse)
def need_to_focus(conn: Annotated[psycopg.Connection, Depends(get_db)]):
    """The one stock that most needs attention: news buzz, an unusual move and a near event."""
    return service.top_focus(conn, datetime.now(IST).date())
