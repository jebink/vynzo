"""Company profiles (sector, industry, shares outstanding) from Yahoo Finance's Ticker.info.

One row per company: the first active listing with a Yahoo symbol supplies it (NSE sorts before
BSE). A failed or empty lookup keeps the company's previous values.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

log = logging.getLogger(__name__)

_COMPANIES = """
SELECT DISTINCT ON (l.company_id) l.company_id, ps.provider_symbol
FROM listings l JOIN provider_symbols ps ON ps.listing_id = l.listing_id AND ps.provider = 'yahoo'
WHERE l.is_active AND l.company_id IS NOT NULL
ORDER BY l.company_id, l.exchange::text DESC
"""
_UPDATE = """
UPDATE companies SET sector = %(sector)s, industry = %(industry)s,
    shares_outstanding = %(shares)s, profile_updated_at = now()
WHERE company_id = %(company_id)s
"""


@dataclass
class ProfilesReport:
    companies: int = 0
    updated: int = 0
    failed: list[str] = field(default_factory=list)


def _default_info(provider_symbol: str) -> dict[str, Any]:
    import yfinance as yf

    return yf.Ticker(provider_symbol).info or {}


def parse_info(info: dict[str, Any]) -> dict[str, Any] | None:
    """sector, industry and shares from Ticker.info; None when Yahoo has none of them."""
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    shares = int(shares) if isinstance(shares, int | float) and shares > 0 else None
    out = {"sector": info.get("sector") or None, "industry": info.get("industry") or None}
    out["shares"] = shares
    return out if any(out.values()) else None


def sync_profiles(
    conn: psycopg.Connection, fetch_info: Callable[[str], dict[str, Any]] | None = None
) -> ProfilesReport:
    """Refresh every active company's profile, committing per company."""
    fetch_info = fetch_info or _default_info
    report = ProfilesReport()
    for row in conn.execute(_COMPANIES).fetchall():
        company_id, symbol = row["company_id"], row["provider_symbol"]
        report.companies += 1
        try:
            profile = parse_info(fetch_info(symbol))
        except Exception:  # one bad ticker must not stop the run
            log.exception("profile lookup failed for %s", symbol)
            profile = None
        if profile is None:
            report.failed.append(symbol)
            continue
        conn.execute(_UPDATE, {**profile, "company_id": company_id})
        conn.commit()
        report.updated += 1
    return report
