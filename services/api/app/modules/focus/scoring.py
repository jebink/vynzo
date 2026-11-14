"""Focus score: how much a stock needs attention right now, 0-100. Pure functions.

Three parts, each with a one-line reason:
- News (max 45): headline volume (8 = full) x the model's confidence x sentiment strength,
  where a strongly positive and a strongly negative story count the same.
- Market (max 35): the last 5 sessions' move against the stock's own normal volatility
  (3 standard deviations = full 25) plus today's volume against its 20-day average (3x = full 10).
- Event (max 20): results or ex-dividend within EVENT_DAYS; today = 20, fading to ~1 at the edge.

Grade: A >= 75, B >= 60, C >= 45, else D.
"""

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

NEWS_MAX, MARKET_MAX, EVENT_MAX = 45.0, 35.0, 20.0
FULL_HEADLINES = 8
FULL_MOVE_SIGMA = 3.0
FULL_RVOL = 3.0
EVENT_DAYS = 14
GRADES = ((75, "A"), (60, "B"), (45, "C"))
EVENT_LABELS = {"results": "Quarterly results", "ex_dividend": "Ex-dividend"}


@dataclass(frozen=True)
class Part:
    points: float
    max: float
    reason: str


@dataclass(frozen=True)
class Performance:
    close: float | None
    change_1d_pct: float | None
    change_5d_pct: float | None
    change_20d_pct: float | None
    move_sigma: float | None  # |5-day move| in standard deviations of its normal 5-day move
    rvol: float | None  # today's volume / previous 20-day average


@dataclass(frozen=True)
class Focus:
    score: int
    grade: str
    news: Part
    market: Part
    event: Part
    performance: Performance = field(default_factory=lambda: Performance(*[None] * 6))


def _pct(new: float, old: float) -> float | None:
    return (new / old - 1) * 100 if old else None


def performance(closes: list[float], volumes: list[float]) -> Performance:
    c = [float(x) for x in closes]
    v = [float(x or 0) for x in volumes]
    if len(c) < 2:
        return Performance(c[-1] if c else None, None, None, None, None, None)
    rets = [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1]]
    base = rets[:-5] if len(rets) > 10 else rets  # normal volatility, before the recent move
    sigma = statistics.pstdev(base) if len(base) > 1 else 0.0
    r5 = c[-1] / c[-6] - 1 if len(c) > 5 and c[-6] else None
    avg_vol = statistics.fmean(v[-21:-1]) if len(v) > 1 else 0.0
    return Performance(
        close=c[-1],
        change_1d_pct=_pct(c[-1], c[-2]),
        change_5d_pct=r5 * 100 if r5 is not None else None,
        change_20d_pct=_pct(c[-1], c[-21]) if len(c) > 20 else None,
        move_sigma=abs(r5) / (sigma * math.sqrt(5)) if r5 is not None and sigma > 0 else None,
        rvol=v[-1] / avg_vol if avg_vol > 0 else None,
    )


def news_part(sentiment: float | None, news: dict | None) -> Part:
    if not news or not news.get("headline_count"):
        return Part(0.0, NEWS_MAX, "No headlines in the last few days")
    count = int(news["headline_count"])
    confidence = float(news.get("confidence") or 0.0)
    strength = abs(float(sentiment or 0.0))
    points = NEWS_MAX * min(1.0, count / FULL_HEADLINES) * confidence * (0.4 + 0.6 * strength)
    label = news.get("label") or "neutral"
    return Part(points, NEWS_MAX, f"{count} headlines, {label} ({sentiment or 0:+.1f})")


def market_part(p: Performance) -> Part:
    move = MARKET_MAX * 25 / 35 * min(1.0, (p.move_sigma or 0.0) / FULL_MOVE_SIGMA)
    vol = MARKET_MAX * 10 / 35 * min(1.0, max(0.0, ((p.rvol or 0.0) - 1) / (FULL_RVOL - 1)))
    bits = []
    if p.change_5d_pct is not None:
        sigma = f" ({p.move_sigma:.1f}σ)" if p.move_sigma is not None else ""
        bits.append(f"{p.change_5d_pct:+.1f}% in 5 sessions{sigma}")
    if p.rvol is not None:
        bits.append(f"volume {p.rvol:.1f}× normal")
    return Part(move + vol, MARKET_MAX, ", ".join(bits) or "Not enough price history")


def event_part(event_type: str | None, event_date: date | None, today: date) -> Part:
    if not event_type or event_date is None:
        return Part(0.0, EVENT_MAX, f"No results or dividend in the next {EVENT_DAYS} days")
    days = (event_date - today).days
    points = EVENT_MAX * max(0.0, 1 - days / (EVENT_DAYS + 1))
    when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
    return Part(points, EVENT_MAX, f"{EVENT_LABELS.get(event_type, event_type)} {when}")


def grade(score: int) -> str:
    return next((g for floor, g in GRADES if score >= floor), "D")


def focus(row: dict, today: date) -> Focus:
    perf = performance(row["closes"], row["volumes"])
    n = news_part(row.get("sentiment"), row.get("news"))
    m = market_part(perf)
    e = event_part(row.get("event_type"), row.get("event_date"), today)
    score = int(round(min(100.0, n.points + m.points + e.points)))
    return Focus(score, grade(score), n, m, e, perf)
