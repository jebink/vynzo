"""Gap detection (ported verbatim from vinzo-core ingest.detect_gaps)."""

from datetime import datetime, timedelta

_FREQ = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "75m": timedelta(minutes=75),
    "1d": timedelta(days=1),
    "1w": timedelta(days=7),
    "1mo": timedelta(days=31),
}


def detect_gaps(ts: list[datetime], timeframe: str) -> list[tuple[datetime, datetime]]:
    """Detect missing bars based on expected frequency (calendar-naive for daily+)."""
    if len(ts) < 2:
        return []
    step = _FREQ.get(timeframe)
    if step is None:
        return []

    # For daily/weekly/monthly flag large holes only
    multiplier = 1.5 if timeframe in {"1m", "5m", "15m", "75m"} else 3.0
    gaps: list[tuple[datetime, datetime]] = []
    for a, b in zip(ts, ts[1:], strict=False):
        delta = b - a
        if delta > step * multiplier:
            # skip obvious weekend/holiday for daily
            if timeframe == "1d" and delta <= timedelta(days=4):
                continue
            gaps.append((a, b))
    return gaps
