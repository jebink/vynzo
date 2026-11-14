"""Business use case for the focus module: rank every active stock, return the top one."""

from dataclasses import asdict
from datetime import date
from typing import Any

import psycopg

from app.modules.focus import repository, scoring

HEADLINES_SHOWN = 4


def _stock(row: dict[str, Any], f: scoring.Focus, today: date) -> dict[str, Any]:
    news = row.get("news") or None
    event = None
    if row.get("event_type"):
        event = {
            "type": row["event_type"],
            "date": row["event_date"],
            "days_away": (row["event_date"] - today).days,
            "details": row.get("event_details") or {},
        }
    return {
        "listing_id": row["listing_id"],
        "exchange": row["exchange"],
        "symbol": row["symbol"],
        "company_name": row.get("company_name"),
        "sector": row.get("sector"),
        "score": f.score,
        "grade": f.grade,
        "parts": {"news": asdict(f.news), "market": asdict(f.market), "event": asdict(f.event)},
        "news": None
        if not news
        else {
            "label": news.get("label"),
            "sentiment": row.get("sentiment"),
            "confidence": news.get("confidence"),
            "summary": news.get("summary"),
            "headline_count": int(news.get("headline_count") or 0),
            "headlines": (news.get("headlines") or [])[:HEADLINES_SHOWN],
        },
        "performance": asdict(f.performance),
        "event": event,
    }


def top_focus(conn: psycopg.Connection, today: date) -> dict[str, Any]:
    """The highest focus score among active equities (ties: more headlines, then symbol)."""
    rows = repository.candidates(conn, today, scoring.EVENT_DAYS)
    if not rows:
        return {"as_of": None, "stock": None}
    scored = [(scoring.focus(r, today), r) for r in rows]
    f, best = max(
        scored,
        key=lambda x: (
            x[0].score,
            (x[1].get("news") or {}).get("headline_count") or 0,
            x[1]["symbol"],
        ),
    )
    return {"as_of": best["latest_ts"], "stock": _stock(best, f, today)}
