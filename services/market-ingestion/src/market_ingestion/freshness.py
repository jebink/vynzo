"""Freshness check: is the newest daily bar recent enough? Optionally pushes to Uptime Kuma."""

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime

import psycopg

from market_ingestion.sessions import IST, expected_latest_session, prev_weekday

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FreshnessResult:
    fresh: bool
    latest: date | None
    expected: date
    pushed: bool | None = None


def _push(push_url: str, fresh: bool, msg: str) -> bool:
    q = urllib.parse.urlencode({"status": "up" if fresh else "down", "msg": msg})
    try:
        with urllib.request.urlopen(f"{push_url}?{q}", timeout=10) as resp:  # noqa: S310
            return bool(json.loads(resp.read().decode()).get("ok", False))
    except Exception as exc:  # noqa: BLE001
        log.warning("kuma push failed: %s", str(exc)[:200])
        return False


def check_freshness(
    conn: psycopg.Connection, *, now: datetime | None = None, push_url: str | None = None
) -> FreshnessResult:
    """Stale if the newest 1d bar is more than one trading day behind (one weekday of slack)."""
    row = conn.execute("SELECT max(ts) AS ts FROM ohlcv_1d").fetchone()
    latest_ts = row["ts"] if row else None
    latest = latest_ts.astimezone(IST).date() if latest_ts else None
    expected = expected_latest_session(now or datetime.now(UTC))
    fresh = latest is not None and latest >= prev_weekday(expected)
    pushed = _push(push_url, fresh, f"latest {latest} expected {expected}") if push_url else None
    return FreshnessResult(fresh=fresh, latest=latest, expected=expected, pushed=pushed)
