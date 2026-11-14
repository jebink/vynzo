"""Run a job: python -m analytics_worker <job> [--days N] [--as-of YYYY-MM-DD]

Each implemented job prints exactly one JSON summary line on stdout; logs go to stderr.
"""

import argparse
import dataclasses
import json
import logging
import sys
from datetime import date
from typing import Any

from analytics_worker.config import Settings
from analytics_worker.db import connect
from analytics_worker.indicators.job import run_indicators
from analytics_worker.signals.high_volume_buy import run_high_volume_buy

FAIL_RATIO = 0.1


def _emit(summary: Any) -> None:
    print(json.dumps(dataclasses.asdict(summary)), flush=True)


def compute_indicators(args: argparse.Namespace, settings: Settings) -> int:
    with connect(settings.database_url) as conn:
        report = run_indicators(conn)
    _emit(report)
    return 1 if len(report.failed) > FAIL_RATIO * report.listings else 0


def high_volume_buy(args: argparse.Namespace, settings: Settings) -> int:
    with connect(settings.database_url) as conn:
        report = run_high_volume_buy(conn, days=args.days, as_of=args.as_of)
    _emit(report)
    return 1 if len(report.failed) > FAIL_RATIO * report.listings else 0


def swing(args: argparse.Namespace, settings: Settings) -> int:
    """Run the swing detector."""
    raise NotImplementedError("swing: not ported yet")


def sentiment(args: argparse.Namespace, settings: Settings) -> int:
    """Fetch news and score sentiment."""
    raise NotImplementedError("sentiment: not ported yet")


JOBS = {
    "indicators": compute_indicators,
    "high-volume-buy": high_volume_buy,
    "swing": swing,
    "sentiment": sentiment,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics_worker")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--days", type=int, default=1, help="high-volume-buy: sessions to scan")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="high-volume-buy: YYYY-MM-DD"
    )
    args = parser.parse_args(argv)
    settings = Settings()
    logging.basicConfig(level=settings.log_level, stream=sys.stderr)
    return JOBS[args.job](args, settings)


if __name__ == "__main__":
    sys.exit(main())
