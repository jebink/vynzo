"""Market regime from NIFTY, BANK NIFTY and India VIX daily bars, in [-1, 1].

The score blends the slow trend (50/200-day EMAs, 60%) with NIFTY's short-term direction
(20-day EMA and 10-session return, 40%). The slow trend alone lags turns by weeks: in a sharp
rally it still reads "bearish" while the market is already rising. `short_term` is exposed on
its own so a pick against the market's current direction is never actionable.
"""

from dataclasses import dataclass, field

import pandas as pd

from analytics_worker.indicators.ta import ema
from analytics_worker.opportunities.features import clip

BULLISH, BEARISH = 0.3, -0.3


@dataclass(frozen=True)
class Regime:
    score: float  # -1 (risk-off, falling market) .. +1 (rising market)
    label: str  # "bullish" | "neutral" | "bearish" | "unknown"
    notes: list[str] = field(default_factory=list)
    short_term: float = 0.0  # NIFTY's direction over the last couple of weeks, -1 .. +1

    def as_json(self) -> dict:
        return {
            "score": round(self.score, 3),
            "label": self.label,
            "notes": self.notes,
            "short_term": round(self.short_term, 3),
        }


def _trend(name: str, bars: pd.DataFrame) -> tuple[float, list[str]]:
    close = bars["close"]
    e50, e200 = ema(close, 50), ema(close, 200)
    c = float(close.iloc[-1])
    above50 = c > float(e50.iloc[-1])
    golden = float(e50.iloc[-1]) > float(e200.iloc[-1])
    rising = len(e50) > 10 and float(e50.iloc[-1]) > float(e50.iloc[-11])
    ret20 = c / float(close.iloc[-21]) - 1.0 if len(close) > 20 else 0.0
    score = (
        0.35 * (1 if above50 else -1)
        + 0.25 * (1 if golden else -1)
        + 0.2 * (1 if rising else -1)
        + 0.2 * clip(ret20 / 0.05)
    )
    notes = [
        f"{name} {'above' if above50 else 'below'} its 50-day EMA, "
        f"50-EMA {'above' if golden else 'below'} 200-EMA, {ret20 * 100:+.1f}% over 20 sessions"
    ]
    return score, notes


def _short_term(bars: pd.DataFrame) -> tuple[float, str]:
    close = bars["close"]
    c, e20 = float(close.iloc[-1]), float(ema(close, 20).iloc[-1])
    ret10 = c / float(close.iloc[-11]) - 1.0 if len(close) > 10 else 0.0
    score = clip(0.5 * (1 if c > e20 else -1) + 0.5 * clip(ret10 / 0.03))
    return score, (
        f"NIFTY {'above' if c > e20 else 'below'} its 20-day EMA, "
        f"{ret10 * 100:+.1f}% over 10 sessions"
    )


def market_regime(
    nifty: pd.DataFrame | None,
    bank_nifty: pd.DataFrame | None = None,
    vix: pd.DataFrame | None = None,
) -> Regime:
    """Trend of NIFTY (70%) and BANK NIFTY (30%) adjusted by the India VIX level and change."""
    if nifty is None or len(nifty) < 60:
        return Regime(0.0, "unknown", ["NIFTY history unavailable; market regime not used"])
    score, notes = _trend("NIFTY", nifty)
    if bank_nifty is not None and len(bank_nifty) >= 60:
        bank_score, bank_notes = _trend("BANK NIFTY", bank_nifty)
        score = 0.7 * score + 0.3 * bank_score
        notes += bank_notes
    short_term, short_note = _short_term(nifty)
    score = 0.6 * score + 0.4 * short_term
    notes.insert(0, short_note)
    if vix is not None and len(vix) >= 6:
        level = float(vix["close"].iloc[-1])
        change = level / float(vix["close"].iloc[-6]) - 1.0
        if level >= 22:
            score -= 0.2
        elif level >= 18:
            score -= 0.1
        elif level < 14:
            score += 0.05
        if change > 0.15:
            score -= 0.15
        notes.append(f"India VIX {level:.1f} ({change * 100:+.0f}% over 5 sessions)")
    score = clip(score)
    label = "bullish" if score >= BULLISH else "bearish" if score <= BEARISH else "neutral"
    return Regime(score, label, notes, short_term)
