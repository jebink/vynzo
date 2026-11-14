"""Persistence for opportunities: SQL against PostgreSQL. Schema lives in database/postgres."""

from typing import Any

import psycopg
from psycopg.rows import dict_row

_ITEM_COLUMNS = """
    o.id, o.listing_id, l.exchange::text AS exchange, l.symbol, c.name AS company_name,
    o.horizon, o.as_of, o.direction, o.status, o.score, o.confidence, o.price, o.entry_low,
    o.entry_high, o.stop_loss, o.targets, o.risk_reward, o.holding_period, o.supports,
    o.resistances, o.reasons, o.factors, o.risks, o.invalidation, o.setups, o.calc_version
    , c.sector, c.shares_outstanding
"""
_FROM = (
    "FROM opportunity o JOIN listings l USING (listing_id) LEFT JOIN companies c USING (company_id)"
)


def latest_session(conn: psycopg.Connection) -> dict[str, Any] | None:
    """as_of, regime and created_at of the newest picks."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT as_of, regime, max(created_at) AS generated_at FROM opportunity "
            "WHERE as_of = (SELECT max(as_of) FROM opportunity) GROUP BY as_of, regime "
            "ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()


def picks_for(conn: psycopg.Connection, as_of: Any) -> list[dict[str, Any]]:
    """All picks of one session, actionable first, then by score."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"SELECT {_ITEM_COLUMNS} {_FROM} WHERE o.as_of = %s "  # noqa: S608 - fixed fragments
            "ORDER BY o.horizon, (o.status = 'actionable') DESC, o.score DESC, l.symbol",
            (as_of,),
        ).fetchall()


def pick(conn: psycopg.Connection, pick_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"SELECT {_ITEM_COLUMNS}, o.regime, o.inputs, "  # noqa: S608 - fixed fragments
            "x.status AS outcome_status, x.entry_at, x.entry_price, x.exit_at, x.exit_price, "
            f"x.return_pct, x.sessions_held {_FROM} "
            "LEFT JOIN opportunity_outcome x ON x.opportunity_id = o.id WHERE o.id = %s",
            (pick_id,),
        ).fetchone()


# A pick that repeats an earlier pick (same listing, horizon and direction) which was still open
# on its date is the same recommendation again, not a new one: the track record skips it.
_NOT_A_REPEAT = """
    NOT EXISTS (
        SELECT 1 FROM opportunity p
        LEFT JOIN opportunity_outcome px ON px.opportunity_id = p.id
        WHERE p.listing_id = o.listing_id AND p.horizon = o.horizon
          AND p.direction = o.direction AND p.status = ANY(%(statuses)s)
          AND p.as_of < o.as_of
          AND (px.opportunity_id IS NULL OR px.exit_at >= o.as_of)
    )
"""


def pick_results(conn: psycopg.Connection, statuses: list[str]) -> list[dict[str, Any]]:
    """horizon, score and outcome (NULL while open) of every pick with one of ``statuses``."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT o.horizon, o.score, x.status, x.return_pct FROM opportunity o "
            "LEFT JOIN opportunity_outcome x ON x.opportunity_id = o.id "
            f"WHERE o.status = ANY(%(statuses)s) AND {_NOT_A_REPEAT}",  # noqa: S608 - fixed SQL
            {"statuses": statuses},
        ).fetchall()


def recent_closed(
    conn: psycopg.Connection, statuses: list[str], limit: int
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT o.id, l.symbol, l.exchange::text AS exchange, o.horizon, o.direction, "
            "o.score, o.as_of, x.status, x.return_pct, x.exit_at "
            "FROM opportunity o JOIN opportunity_outcome x ON x.opportunity_id = o.id "
            "JOIN listings l USING (listing_id) "
            f"WHERE o.status = ANY(%(statuses)s) AND {_NOT_A_REPEAT} "  # noqa: S608 - fixed SQL
            "ORDER BY x.evaluated_at DESC, o.id DESC LIMIT %(limit)s",
            {"statuses": statuses, "limit": limit},
        ).fetchall()
