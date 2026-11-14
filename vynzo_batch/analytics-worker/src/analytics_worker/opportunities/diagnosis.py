"""Why a backtest trade lost: measurable causes from the bars, NIFTY and the regime. Pure.

Each reason is a stable `code` (the UI counts them across trades to show where a strategy
leaks) plus a sentence with the numbers for that trade. Only entered trades that lost get any.
"""

from dataclasses import dataclass

import pandas as pd

ATR_DAYS = 14
SMA_DAYS = 20
VOL_LOOKBACK = 250

MARKET_DRAG_PCT = 2.0  # NIFTY moved at least this much against the trade
CHASE_PCT = 5.0  # entry this far beyond the 20-day average, in the trade's direction
GIVEBACK_MIN_PCT = 2.0  # open profit at least this big (and at least the final loss) was lost
VOL_SPIKE = 1.5  # ATR% this many times its 1-year median


@dataclass(frozen=True)
class Reason:
    code: str
    text: str


def features(bars: pd.DataFrame) -> pd.DataFrame:
    """Per session: ATR % of close, its 1-year median, and the 20-day average close."""
    prev = bars["close"].shift()
    tr = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    atr_pct = tr.rolling(ATR_DAYS).mean() / bars["close"] * 100
    return pd.DataFrame(
        {
            "atr_pct": atr_pct,
            "atr_median": atr_pct.rolling(VOL_LOOKBACK, min_periods=60).median(),
            "sma": bars["close"].rolling(SMA_DAYS).mean(),
        }
    )


def loss_reasons(
    item, bars: pd.DataFrame, feats: pd.DataFrame, benchmark: pd.Series | None
) -> list[Reason]:
    """Reasons a losing entered trade lost, most actionable first; [] for anything else."""
    o = item.outcome
    if o is None or o.return_pct is None or o.return_pct >= 0 or o.entry_at is None:
        return []
    d = 1 if item.direction == "BUY" else -1
    side = "BUY" if d > 0 else "SELL"
    entry, exit_at = float(o.entry_price), o.exit_at
    at_signal = feats.loc[: item.as_of].iloc[-1] if not feats.loc[: item.as_of].empty else None
    held = bars.loc[o.entry_at : exit_at]
    out: list[Reason] = []

    if o.status == "stopped" and exit_at in bars.index:
        stop, open_ = float(o.exit_price), float(bars.at[exit_at, "open"])
        beyond = d * (stop - open_) / stop * 100
        if beyond > 0:
            out.append(
                Reason(
                    "gap_through_stop",
                    f"Gapped {beyond:.1f}% through the stop at the open: "
                    "a real fill would have lost more than shown",
                )
            )
        stop_pct = abs(entry - stop) / entry * 100
        if (
            at_signal is not None
            and pd.notna(at_signal["atr_pct"])
            and stop_pct < at_signal["atr_pct"]
        ):
            out.append(
                Reason(
                    "tight_stop",
                    f"Stop was {stop_pct:.1f}% away, inside one normal day's range "
                    f"(ATR {at_signal['atr_pct']:.1f}%)",
                )
            )

    if len(held):
        best = held["high"].max() if d > 0 else held["low"].min()
        mfe = d * (float(best) - entry) / entry * 100
        if mfe >= max(GIVEBACK_MIN_PCT, abs(o.return_pct)):
            out.append(
                Reason(
                    "gave_back_profit",
                    f"Was up {mfe:.1f}% before reversing: "
                    "no trailing stop or partial profit-taking",
                )
            )

    if item.regime == ("bearish" if d > 0 else "bullish"):
        out.append(Reason("against_regime", f"{side} while the market regime was {item.regime}"))

    if benchmark is not None and exit_at is not None:
        start, end = benchmark.asof(o.entry_at), benchmark.asof(exit_at)
        if start > 0 and end > 0:
            move = d * (end / start - 1) * 100
            if move <= -MARKET_DRAG_PCT:
                out.append(
                    Reason(
                        "market_drag",
                        f"NIFTY moved {abs(move):.1f}% against the trade: a market-wide move",
                    )
                )

    if at_signal is not None and pd.notna(at_signal["sma"]):
        stretch = d * (entry / at_signal["sma"] - 1) * 100
        if stretch >= CHASE_PCT:
            where = "above" if d > 0 else "below"
            out.append(
                Reason(
                    "chased_entry",
                    f"Entered {stretch:.1f}% {where} the 20-day average: chasing an extended move",
                )
            )
        if (
            pd.notna(at_signal["atr_median"])
            and at_signal["atr_pct"] >= VOL_SPIKE * at_signal["atr_median"]
        ):
            ratio = at_signal["atr_pct"] / at_signal["atr_median"]
            out.append(
                Reason(
                    "volatility_spike",
                    f"Volatility was {ratio:.1f}x its 1-year normal at the signal",
                )
            )

    if o.status == "expired":
        out.append(
            Reason(
                "no_follow_through",
                "No follow-through: the time limit hit with the trade still under water",
            )
        )

    return out or [
        Reason("stock_specific", "No measurable cause: a stock-specific move against the trade")
    ]
