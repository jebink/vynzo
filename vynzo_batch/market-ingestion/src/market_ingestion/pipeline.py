"""The EOD pipeline: fetch, store raw, normalize, validate, upsert, record gaps, audit.

The pipeline owns transactions: each (listing, timeframe) is one transaction, committed on
success. On failure it is rolled back and the error run row is written in a fresh transaction,
so the audit trail survives the rollback.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import psycopg
from psycopg import sql

from market_ingestion.checkpoint.store import fetch_start, finish_run, last_bar_ts, start_run
from market_ingestion.db import connect
from market_ingestion.instruments.registry import ActiveListing, active_listings, find_listing
from market_ingestion.normalization.bars import normalize
from market_ingestion.providers.base import Provider
from market_ingestion.publisher.store import insert_raw, record_gaps, upsert_bars
from market_ingestion.recovery.gaps import detect_gaps
from market_ingestion.sessions import last_complete_session
from market_ingestion.timeframes import EOD_TIMEFRAMES, TIMEFRAMES
from market_ingestion.validation.bars import validate_bars

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TimeframeResult:
    listing_id: int
    timeframe: str
    rows: int
    gaps: int
    status: str
    error: str | None = None


@dataclass(frozen=True)
class EodReport:
    listings: int
    failed: list[str] = field(default_factory=list)
    rows: int = 0


def _label(listing: ActiveListing) -> str:
    return f"{listing.exchange}:{listing.symbol}"


def _guarded(
    conn: psycopg.Connection,
    provider: Provider,
    listing: ActiveListing,
    timeframe: str,
    work: Callable[[int], tuple[int, int]],
) -> TimeframeResult:
    """Run `work(run_id) -> (rows, gaps)` in one transaction with an ingest_runs row."""
    try:
        run_id = start_run(conn, listing.listing_id, provider.name, timeframe)
        rows, gaps = work(run_id)
        finish_run(conn, run_id, rows=rows, gaps=gaps, status="ok")
        conn.commit()
        return TimeframeResult(listing.listing_id, timeframe, rows, gaps, "ok", None)
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        note = str(exc)[:300]
        log.warning("ingest failed for %s %s: %s", _label(listing), timeframe, note)
        run_id = start_run(conn, listing.listing_id, provider.name, timeframe)
        finish_run(conn, run_id, rows=0, gaps=0, status="error", notes=note)
        conn.commit()
        return TimeframeResult(listing.listing_id, timeframe, 0, 0, "error", note)


def _store_window(
    conn: psycopg.Connection,
    provider: Provider,
    listing: ActiveListing,
    timeframe: str,
    run_id: int,
    start: date | None,
    end: date,
    last_session: date,
    *,
    detect: bool,
) -> tuple[int, int]:
    records = provider.fetch_bars(listing.provider_symbol, timeframe, start, end)
    insert_raw(conn, run_id, records)
    bars = validate_bars(normalize(records, listing.listing_id), last_session)
    rows = upsert_bars(conn, timeframe, bars)
    gaps = 0
    if detect:
        gaps = record_gaps(
            conn, listing.listing_id, timeframe, detect_gaps([b.ts for b in bars], timeframe)
        )
    return rows, gaps


def ingest_listing(
    conn: psycopg.Connection,
    provider: Provider,
    listing: ActiveListing,
    timeframe: str,
    end: date,
) -> TimeframeResult:
    """Ingest one (listing, timeframe) from its checkpoint to `end` in one transaction."""

    def work(run_id: int) -> tuple[int, int]:
        start = fetch_start(timeframe, last_bar_ts(conn, listing.listing_id, timeframe))
        return _store_window(
            conn, provider, listing, timeframe, run_id, start, end, end, detect=True
        )

    return _guarded(conn, provider, listing, timeframe, work)


def _run_listings(
    db_url: str,
    listings: list[ActiveListing],
    task: Callable[[psycopg.Connection, ActiveListing], list[TimeframeResult]],
    workers: int,
) -> EodReport:
    def one(listing: ActiveListing) -> tuple[ActiveListing, list[TimeframeResult]]:
        # Anything escaping the per-timeframe guard (connect failure, a failed error-row write)
        # becomes failed results for this listing, so the job still reports and applies the
        # failure-ratio rule instead of dying in the pool.
        try:
            conn = connect(db_url)  # one connection per task; never shared across threads
            try:
                return listing, task(conn, listing)
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            note = str(exc)[:300] or type(exc).__name__
            log.warning("listing %s failed: %s", _label(listing), note)
            return listing, [
                TimeframeResult(listing.listing_id, tf, 0, 0, "error", note)
                for tf in EOD_TIMEFRAMES
            ]

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        outcomes = list(pool.map(one, listings))
    failed = [_label(lst) for lst, res in outcomes if any(r.status == "error" for r in res)]
    rows = sum(r.rows for _, res in outcomes for r in res)
    return EodReport(listings=len(listings), failed=failed, rows=rows)


def run_eod(
    db_url: str,
    provider: Provider,
    *,
    workers: int = 4,
    now: datetime | None = None,
    only: list[ActiveListing] | None = None,
) -> EodReport:
    """Bring every active listing up to the last complete session."""
    end = last_complete_session(now or datetime.now(UTC))
    if only is None:
        with connect(db_url) as conn:
            only = active_listings(conn, provider.name)

    def task(conn: psycopg.Connection, listing: ActiveListing) -> list[TimeframeResult]:
        return [ingest_listing(conn, provider, listing, tf, end) for tf in EOD_TIMEFRAMES]

    return _run_listings(db_url, only, task, workers)


def _gap_resolved(conn: psycopg.Connection, listing_id: int, timeframe: str, gap: dict) -> bool:
    query = sql.SQL(
        "SELECT EXISTS (SELECT 1 FROM {} WHERE listing_id = %s AND ts > %s AND ts < %s) AS ok"
    ).format(sql.Identifier(TIMEFRAMES[timeframe].table))
    row = conn.execute(query, (listing_id, gap["gap_start"], gap["gap_end"])).fetchone()
    return bool(row and row["ok"])


def run_backfill(
    db_url: str,
    provider: Provider,
    *,
    listing: str | None = None,
    now: datetime | None = None,
    workers: int = 1,
) -> EodReport:
    """Re-fetch unresolved gap windows and full history for listings missing a timeframe."""
    end = last_complete_session(now or datetime.now(UTC))
    with connect(db_url) as conn:
        if listing is None:
            targets = active_listings(conn, provider.name)
        else:
            exchange, _, symbol = listing.partition(":")
            found = find_listing(conn, exchange, symbol, provider.name)
            targets = [found] if found else []

    def task(conn: psycopg.Connection, lst: ActiveListing) -> list[TimeframeResult]:
        results: list[TimeframeResult] = []
        gaps = conn.execute(
            "SELECT id, timeframe, gap_start, gap_end FROM ohlcv_gaps "
            "WHERE listing_id = %s AND NOT resolved ORDER BY id",
            (lst.listing_id,),
        ).fetchall()
        conn.rollback()  # end the read transaction
        for gap in gaps:
            tf = gap["timeframe"]
            if tf not in EOD_TIMEFRAMES:
                continue

            def work(run_id: int, gap=gap, tf=tf) -> tuple[int, int]:
                rows, _ = _store_window(
                    conn,
                    provider,
                    lst,
                    tf,
                    run_id,
                    gap["gap_start"].date(),
                    gap["gap_end"].date(),
                    end,
                    detect=False,
                )
                if _gap_resolved(conn, lst.listing_id, tf, gap):
                    conn.execute(
                        "UPDATE ohlcv_gaps SET resolved = true WHERE id = %s", (gap["id"],)
                    )
                return rows, 0

            results.append(_guarded(conn, provider, lst, tf, work))
        for tf in EOD_TIMEFRAMES:
            has_bars = last_bar_ts(conn, lst.listing_id, tf) is not None
            conn.rollback()
            if not has_bars:
                results.append(ingest_listing(conn, provider, lst, tf, end))
        return results

    return _run_listings(db_url, targets, task, workers)
