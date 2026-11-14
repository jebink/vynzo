"""opportunities and opportunity-outcomes jobs: the only I/O in this package.

`run_opportunities` scores every active equity listing whose newest bar is the latest session
and replaces that session's picks per horizon. `run_outcomes` closes open picks against the
bars that came after them. Both own their transactions.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from analytics_worker.db import load_daily_bars
from analytics_worker.opportunities.engine import CALC_VERSION, Opportunity, score_listing
from analytics_worker.opportunities.outcomes import OUTCOME_VERSION, evaluate_outcome
from analytics_worker.opportunities.regime import Regime, market_regime

log = logging.getLogger(__name__)

# NSE listings first, so a company listed on both exchanges is scored once, on NSE.
LISTINGS_SQL = """
SELECT l.listing_id, l.company_id
FROM listings l
WHERE l.is_active AND l.kind = 'equity'
  AND EXISTS (SELECT 1 FROM ohlcv_1d b WHERE b.listing_id = l.listing_id)
ORDER BY (l.exchange = 'NSE') DESC, l.listing_id
"""

INDEX_SQL = "SELECT listing_id FROM listings WHERE exchange = 'NSE' AND symbol = %s"

DELETE_SQL = """
DELETE FROM opportunity o
WHERE o.as_of = %(as_of)s
  AND NOT EXISTS (SELECT 1 FROM opportunity_outcome x WHERE x.opportunity_id = o.id)
"""

_COLUMNS = (
    "listing_id, horizon, as_of, direction, status, score, confidence, price, entry_low, "
    "entry_high, stop_loss, targets, risk_reward, holding_period, max_sessions, supports, "
    "resistances, reasons, factors, risks, invalidation, regime, inputs, calc_version"
).split(", ")
INSERT_SQL = (
    f"INSERT INTO opportunity ({', '.join(_COLUMNS)}) "  # noqa: S608 - fixed column list
    f"VALUES ({', '.join(f'%({c})s' for c in _COLUMNS)}) "
    "ON CONFLICT (listing_id, horizon, as_of) DO NOTHING"
)

OPEN_PICKS_SQL = """
SELECT o.id, o.listing_id, o.horizon, o.as_of, o.direction, o.entry_low, o.entry_high,
       o.stop_loss, o.targets, o.max_sessions
FROM opportunity o
WHERE NOT EXISTS (SELECT 1 FROM opportunity_outcome x WHERE x.opportunity_id = o.id)
ORDER BY o.listing_id, o.as_of
"""

OUTCOME_SQL = """
INSERT INTO opportunity_outcome
    (opportunity_id, status, entry_at, entry_price, exit_at, exit_price, return_pct,
     sessions_held, calc_version)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (opportunity_id) DO NOTHING
"""


@dataclass
class OpportunityReport:
    as_of: str | None
    listings: int
    evaluated: int = 0
    stale: int = 0
    skipped_duplicates: int = 0
    found: dict[str, int] = field(default_factory=dict)
    regime: str = "unknown"
    failed: list[int] = field(default_factory=list)


@dataclass
class OutcomeReport:
    open_picks: int
    closed: dict[str, int] = field(default_factory=dict)
    failed: list[int] = field(default_factory=list)


def _until(bars: pd.DataFrame, session: pd.Timestamp) -> pd.DataFrame:
    # An empty frame from load_daily_bars has no datetime index to compare.
    return bars if bars.empty else bars[bars.index <= session]


def _index_bars(
    conn: psycopg.Connection, symbol: str, session: pd.Timestamp
) -> pd.DataFrame | None:
    row = conn.execute(INDEX_SQL, (symbol,)).fetchone()
    if row is None:
        return None
    bars = _until(load_daily_bars(conn, row["listing_id"]), session)
    return bars if not bars.empty else None


def _latest_session(conn: psycopg.Connection, as_of: date | None) -> pd.Timestamp | None:
    if as_of is not None:
        return pd.Timestamp(as_of, tz="UTC")
    row = conn.execute("SELECT max(ts) AS ts FROM ohlcv_1d").fetchone()
    return pd.Timestamp(row["ts"]) if row and row["ts"] is not None else None


def _row(listing_id: int, session: pd.Timestamp, opp: Opportunity, regime: Regime) -> dict:
    return {
        "listing_id": listing_id,
        "horizon": opp.horizon,
        "as_of": session.to_pydatetime(),
        "direction": opp.direction,
        "status": opp.status,
        "score": opp.score,
        "confidence": opp.confidence,
        "price": opp.price,
        "entry_low": opp.entry_low,
        "entry_high": opp.entry_high,
        "stop_loss": opp.stop_loss,
        "targets": opp.targets,
        "risk_reward": opp.risk_reward,
        "holding_period": opp.holding_period,
        "max_sessions": opp.max_sessions,
        "supports": opp.supports,
        "resistances": opp.resistances,
        "reasons": Jsonb(opp.reasons),
        "factors": Jsonb(
            [
                {"group": x.group, "score": round(x.score, 3), "reason": x.reason}
                for x in opp.factors
            ]
        ),
        "risks": Jsonb(opp.risks),
        "invalidation": Jsonb(opp.invalidation),
        "regime": Jsonb(regime.as_json()),
        "inputs": Jsonb(opp.inputs),
        "calc_version": CALC_VERSION,
    }


def run_opportunities(conn: psycopg.Connection, *, as_of: date | None = None) -> OpportunityReport:
    """Score the latest session (or ``as_of``) for every horizon and replace its picks."""
    session = _latest_session(conn, as_of)
    listings = conn.execute(LISTINGS_SQL).fetchall()
    if session is None:
        conn.commit()
        return OpportunityReport(as_of=None, listings=0)

    nifty = _index_bars(conn, "NIFTY", session)
    regime = market_regime(
        nifty, _index_bars(conn, "BANKNIFTY", session), _index_bars(conn, "INDIAVIX", session)
    )
    benchmark = nifty["close"] if nifty is not None else None
    report = OpportunityReport(
        as_of=session.date().isoformat(), listings=len(listings), regime=regime.label
    )
    found: Counter[str] = Counter()
    rows: list[dict] = []
    seen_companies: set[int] = set()

    for item in listings:
        lid, company = item["listing_id"], item["company_id"]
        if company is not None and company in seen_companies:
            report.skipped_duplicates += 1
            continue
        try:
            bars = _until(load_daily_bars(conn, lid), session)
            if bars.empty or bars.index[-1] != session:
                report.stale += 1
                continue
            if company is not None:
                seen_companies.add(company)
            picks = score_listing(bars, benchmark, regime)
            if picks is None:
                continue
            report.evaluated += 1
            for opp in picks:
                rows.append(_row(lid, session, opp, regime))
                found[opp.horizon] += 1
        except Exception:
            conn.rollback()  # the loop only reads, so nothing is lost
            log.exception("opportunities failed for listing %s", lid)
            report.failed.append(lid)

    # Replace the session's picks in one transaction; picks that already have an outcome stay.
    conn.execute(DELETE_SQL, {"as_of": session.to_pydatetime()})
    if rows:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, rows)
    conn.commit()
    report.found = dict(found)
    return report


def run_outcomes(conn: psycopg.Connection) -> OutcomeReport:
    """Close every open pick whose later bars decide it; picks still open are left alone."""
    picks = conn.execute(OPEN_PICKS_SQL).fetchall()
    conn.commit()
    report = OutcomeReport(open_picks=len(picks))
    closed: Counter[str] = Counter()
    by_listing: dict[int, list[dict]] = {}
    for pick in picks:
        by_listing.setdefault(pick["listing_id"], []).append(pick)

    for lid, items in by_listing.items():
        try:
            bars = load_daily_bars(conn, lid)
            if bars.empty:
                continue
            rows = []
            for pick in items:
                future = bars[bars.index > pd.Timestamp(pick["as_of"])]
                outcome = evaluate_outcome(pick, future)
                if outcome is None:
                    continue
                rows.append(
                    (
                        pick["id"],
                        outcome.status,
                        _dt(outcome.entry_at),
                        outcome.entry_price,
                        _dt(outcome.exit_at),
                        outcome.exit_price,
                        outcome.return_pct,
                        outcome.sessions_held,
                        OUTCOME_VERSION,
                    )
                )
                closed[outcome.status] += 1
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(OUTCOME_SQL, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            log.exception("opportunity outcomes failed for listing %s", lid)
            report.failed.append(lid)
    report.closed = dict(closed)
    return report


def _dt(ts: pd.Timestamp | None):
    return ts.to_pydatetime() if ts is not None else None
