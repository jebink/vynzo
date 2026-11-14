"""Run a job: python -m market_ingestion <job> [--listing EXCH:SYM]

Each job prints exactly one JSON summary line on stdout; logs go to stderr.
"""

import argparse
import dataclasses
import json
import logging
import sys
from datetime import UTC, date, datetime
from typing import Any

from market_ingestion.config import REPO_ROOT, Settings
from market_ingestion.db import connect
from market_ingestion.freshness import check_freshness
from market_ingestion.instruments.reference import sync_reference
from market_ingestion.instruments.registry import find_listing
from market_ingestion.pipeline import EodReport, run_backfill, run_eod
from market_ingestion.providers.vendor.yahoo import YahooProvider

FAIL_RATIO = 0.1


def _emit(summary: Any) -> None:
    def default(o: Any) -> str:
        if isinstance(o, date | datetime):
            return o.isoformat()
        raise TypeError(f"not JSON serializable: {type(o)}")

    print(json.dumps(dataclasses.asdict(summary), default=default), flush=True)


def _report_code(report: EodReport) -> int:
    return 1 if len(report.failed) > FAIL_RATIO * report.listings else 0


def eod_ingest(args: argparse.Namespace, settings: Settings) -> int:
    only = None
    if args.listing:
        exchange, _, symbol = args.listing.partition(":")
        with connect(settings.database_url) as conn:
            found = find_listing(conn, exchange, symbol)
        only = [found] if found else []
    report = run_eod(
        settings.database_url,
        YahooProvider(),
        workers=settings.workers,
        now=datetime.now(UTC),
        only=only,
    )
    _emit(report)
    return _report_code(report)


def backfill(args: argparse.Namespace, settings: Settings) -> int:
    report = run_backfill(
        settings.database_url,
        YahooProvider(),
        listing=args.listing,
        now=datetime.now(UTC),
        workers=settings.workers,
    )
    _emit(report)
    return _report_code(report)


def freshness(args: argparse.Namespace, settings: Settings) -> int:
    with connect(settings.database_url) as conn:
        result = check_freshness(conn, now=datetime.now(UTC), push_url=settings.kuma_push_url)
    _emit(result)
    return 0 if result.fresh else 1


def sync_reference_job(args: argparse.Namespace, settings: Settings) -> int:
    ref = REPO_ROOT / "data" / "reference"
    with connect(settings.database_url) as conn:
        report = sync_reference(conn, ref / "nse_equities.csv", ref / "bse_all_equities.csv")
        conn.commit()
    _emit(report)
    return 0


JOBS = {
    "eod": eod_ingest,
    "backfill": backfill,
    "freshness": freshness,
    "sync-reference": sync_reference_job,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market_ingestion")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument(
        "--listing", metavar="EXCH:SYM", help="restrict eod/backfill to one listing"
    )
    args = parser.parse_args(argv)
    settings = Settings()
    logging.basicConfig(level=settings.log_level, stream=sys.stderr)
    return JOBS[args.job](args, settings)


if __name__ == "__main__":
    sys.exit(main())
