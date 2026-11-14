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

import pandas as pd

from analytics_worker.config import Settings
from analytics_worker.db import connect
from analytics_worker.indicators.job import run_indicators
from analytics_worker.opportunities.backtest import dedupe, run_backtest, summarize
from analytics_worker.opportunities.job import run_opportunities, run_outcomes
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


def opportunities(args: argparse.Namespace, settings: Settings) -> int:
    """Rank BUY/SELL opportunities for the latest session (or --as-of) per horizon."""
    with connect(settings.database_url) as conn:
        report = run_opportunities(conn, as_of=args.as_of)
    _emit(report)
    return 1 if report.listings and len(report.failed) > FAIL_RATIO * report.listings else 0


def opportunity_outcomes(args: argparse.Namespace, settings: Settings) -> int:
    """Close open opportunities whose later bars hit the stop, the target or the time limit."""
    with connect(settings.database_url) as conn:
        report = run_outcomes(conn)
    _emit(report)
    return 1 if report.failed else 0


def backtest(args: argparse.Namespace, settings: Settings) -> int:
    """Walk-forward backtest of the opportunity engine (read-only). Needs --start and --end."""
    if args.start is None or args.end is None:
        raise SystemExit("backtest needs --start and --end (YYYY-MM-DD)")
    split = args.split or args.start
    with connect(settings.database_url) as conn:
        picks, _ = run_backtest(conn, start=args.start, end=args.end, workers=args.workers)
    rows = summarize(dedupe(picks), split=pd.Timestamp(split, tz="UTC"))
    print(json.dumps({"picks": len(picks), "groups": rows}, default=str), flush=True)
    return 0


def swing(args: argparse.Namespace, settings: Settings) -> int:
    """Run the swing detector."""
    raise NotImplementedError("swing: not ported yet")


def sentiment(args: argparse.Namespace, settings: Settings) -> int:
    """Fetch news and score sentiment."""
    raise NotImplementedError("sentiment: not ported yet")


JOBS = {
    "indicators": compute_indicators,
    "high-volume-buy": high_volume_buy,
    "opportunities": opportunities,
    "opportunity-outcomes": opportunity_outcomes,
    "backtest": backtest,
    "swing": swing,
    "sentiment": sentiment,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analytics_worker")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--days", type=int, default=1, help="high-volume-buy: sessions to scan")
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="high-volume-buy, opportunities: YYYY-MM-DD",
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, default=None, help="backtest: first session"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, default=None, help="backtest: last session"
    )
    parser.add_argument(
        "--split", type=date.fromisoformat, default=None, help="backtest: out-of-sample from"
    )
    parser.add_argument("--workers", type=int, default=8, help="backtest: processes")
    args = parser.parse_args(argv)
    settings = Settings()
    logging.basicConfig(level=settings.log_level, stream=sys.stderr)
    return JOBS[args.job](args, settings)


if __name__ == "__main__":
    sys.exit(main())
