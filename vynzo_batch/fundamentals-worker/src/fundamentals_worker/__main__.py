"""Run a job: python -m fundamentals_worker <job>"""

import argparse
import logging

from fundamentals_worker.config import Settings


def ingest_statements() -> None:
    """Ingest quarterly/annual financial statements."""
    raise NotImplementedError("ingest_statements: not ported yet")


def ingest_corporate_actions() -> None:
    """Ingest corporate actions."""
    raise NotImplementedError("ingest_corporate_actions: not ported yet")


JOBS = {
    "statements": ingest_statements,
    "corporate-actions": ingest_corporate_actions,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fundamentals_worker")
    parser.add_argument("job", choices=sorted(JOBS))
    args = parser.parse_args(argv)
    logging.basicConfig(level=Settings().log_level)
    JOBS[args.job]()


if __name__ == "__main__":
    main()
