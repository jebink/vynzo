"""Run a job: python -m fundamentals_worker <job>

Each implemented job prints exactly one JSON summary line on stdout; logs go to stderr.
"""

import argparse
import dataclasses
import json
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from fundamentals_worker.config import Settings
from fundamentals_worker.statements.yahoo import sync_fundamentals

FAIL_RATIO = 0.2  # Yahoo lacks fundamentals for some small NSE companies
IST = ZoneInfo("Asia/Kolkata")


def fundamentals(settings: Settings) -> int:
    """Ratio snapshot, annual revenue / net income and dividends per company (Yahoo Finance)."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        report = sync_fundamentals(conn, datetime.now(IST).date())
    print(json.dumps(dataclasses.asdict(report)), flush=True)
    return 1 if report.companies and len(report.failed) > FAIL_RATIO * report.companies else 0


def ingest_corporate_actions(settings: Settings) -> int:
    """Ingest corporate actions."""
    raise NotImplementedError("ingest_corporate_actions: not ported yet")


JOBS = {
    "fundamentals": fundamentals,
    "corporate-actions": ingest_corporate_actions,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fundamentals_worker")
    parser.add_argument("job", choices=sorted(JOBS))
    args = parser.parse_args(argv)
    settings = Settings()
    logging.basicConfig(level=settings.log_level, stream=sys.stderr)
    return JOBS[args.job](settings)


if __name__ == "__main__":
    sys.exit(main())
