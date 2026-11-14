"""Upcoming corporate events (quarterly results, ex-dividend) from Yahoo Finance's Ticker.calendar.

One lookup per company, stored on the listing that supplied the Yahoo symbol (NSE before BSE).
Each run replaces that listing's rows; a failed lookup keeps its previous rows.
Yahoo has no upcoming splits or bonuses; those need an exchange feed.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

SOURCE = "yahoo"

_LISTINGS = """
SELECT DISTINCT ON (l.company_id) l.listing_id, ps.provider_symbol
FROM listings l JOIN provider_symbols ps ON ps.listing_id = l.listing_id AND ps.provider = 'yahoo'
WHERE l.is_active AND l.kind = 'equity' AND l.company_id IS NOT NULL
ORDER BY l.company_id, l.exchange::text DESC
"""
_DELETE = "DELETE FROM corporate_event WHERE listing_id = %(listing_id)s AND source = %(source)s"
_INSERT = """
INSERT INTO corporate_event (listing_id, event_type, event_date, details, source)
VALUES (%(listing_id)s, %(event_type)s, %(event_date)s, %(details)s, %(source)s)
ON CONFLICT (listing_id, event_type, event_date) DO UPDATE
SET details = EXCLUDED.details, source = EXCLUDED.source, updated_at = now()
"""


@dataclass
class EventsReport:
    listings: int = 0
    updated: int = 0
    events: int = 0
    failed: list[str] = field(default_factory=list)


def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def parse_calendar(
    calendar: dict[str, Any], today: date, dividend_amount: Callable[[date], float | None]
) -> list[dict[str, Any]]:
    """Upcoming events from Ticker.calendar; the dividend amount is fetched only when upcoming."""
    events: list[dict[str, Any]] = []
    earnings = calendar.get("Earnings Date") or []
    raw = earnings if isinstance(earnings, list) else [earnings]
    dates = sorted(d for d in map(_as_date, raw) if d)
    if dates and dates[0] >= today:
        details: dict[str, Any] = {}
        if len(dates) > 1 and dates[-1] != dates[0]:
            details["window_end"] = dates[-1].isoformat()  # Yahoo gives a range when unconfirmed
        eps = calendar.get("Earnings Average")
        if isinstance(eps, int | float):
            details["eps_estimate"] = round(float(eps), 2)
        events.append({"event_type": "results", "event_date": dates[0], "details": details})
    ex_div = _as_date(calendar.get("Ex-Dividend Date"))
    if ex_div and ex_div >= today:
        amount = dividend_amount(ex_div)
        details = {"amount": amount} if amount else {}
        events.append({"event_type": "ex_dividend", "event_date": ex_div, "details": details})
    return events


def _default_lookup(provider_symbol: str, today: date) -> list[dict[str, Any]]:
    import yfinance as yf

    ticker = yf.Ticker(provider_symbol)

    def amount(ex_date: date) -> float | None:
        divs = ticker.dividends
        hit = [float(v) for ts, v in divs.items() if ts.date() == ex_date]
        return hit[0] if hit else None

    return parse_calendar(ticker.calendar or {}, today, amount)


def sync_events(
    conn: psycopg.Connection,
    today: date,
    lookup: Callable[[str, date], list[dict[str, Any]]] | None = None,
) -> EventsReport:
    """Refresh every active company's upcoming events, committing per listing."""
    lookup = lookup or _default_lookup
    report = EventsReport()
    for row in conn.execute(_LISTINGS).fetchall():
        listing_id, symbol = row["listing_id"], row["provider_symbol"]
        report.listings += 1
        try:
            events = lookup(symbol, today)
        except Exception:  # one bad ticker must not stop the run
            log.exception("events lookup failed for %s", symbol)
            report.failed.append(symbol)
            continue
        key = {"listing_id": listing_id, "source": SOURCE}
        conn.execute(_DELETE, key)
        for e in events:
            conn.execute(_INSERT, {**key, **e, "details": Jsonb(e["details"])})
        conn.commit()
        report.updated += 1
        report.events += len(events)
    return report
