"""Bar validation (ported from vinzo-core ingest.validate_ohlcv)."""

from datetime import date

from market_ingestion.normalization.bars import Bar
from market_ingestion.sessions import IST


def _consistent(b: Bar) -> bool:
    return not (
        b.high < b.low
        or b.high < b.open
        or b.high < b.close
        or b.low > b.open
        or b.low > b.close
        or b.volume < 0
    )


def validate_bars(bars: list[Bar], last_session: date) -> list[Bar]:
    """Drop inconsistent bars, volume<0 and bars after `last_session` (IST date).

    Dedupes by ts keeping the last occurrence; returns bars sorted by ts.
    """
    by_ts: dict = {}
    for b in bars:
        if not _consistent(b):
            continue
        if b.ts.astimezone(IST).date() > last_session:
            continue
        by_ts.pop(b.ts, None)  # keep-last semantics
        by_ts[b.ts] = b
    return sorted(by_ts.values(), key=lambda b: b.ts)
