from types import SimpleNamespace

import pandas as pd
import pytest
from analytics_worker.opportunities.diagnosis import features, loss_reasons
from analytics_worker.opportunities.outcomes import Outcome

DAYS = pd.date_range("2025-01-01", periods=300, freq="B", tz="UTC")


def flat_bars(close=100.0, spread=1.0):
    return pd.DataFrame(
        {"open": close, "high": close + spread, "low": close - spread, "close": close, "volume": 1},
        index=DAYS,
    )


def trade(outcome, direction="BUY", regime="neutral", as_of_i=250):
    return SimpleNamespace(outcome=outcome, direction=direction, regime=regime, as_of=DAYS[as_of_i])


def codes(item, bars, benchmark=None):
    return [r.code for r in loss_reasons(item, bars, features(bars), benchmark)]


def stopped(entry, stop, entry_i=251, exit_i=253):
    return Outcome(
        "stopped", DAYS[entry_i], entry, DAYS[exit_i], stop, (stop - entry) / entry * 100, 3
    )


def test_winners_and_unfilled_get_no_reasons():
    bars = flat_bars()
    win = Outcome("target_hit", DAYS[251], 100.0, DAYS[253], 104.0, 4.0, 3)
    assert codes(trade(win), bars) == []
    assert codes(trade(Outcome("not_triggered")), bars) == []
    assert codes(trade(None), bars) == []


def test_gap_through_tight_stop():
    bars = flat_bars(spread=2.0)  # ATR ~4%
    bars.loc[DAYS[253], ["open", "low"]] = [95.0, 94.0]  # opens below the 98 stop
    assert codes(trade(stopped(100.0, 98.0)), bars)[:2] == ["gap_through_stop", "tight_stop"]


def test_gave_back_profit_and_against_regime():
    bars = flat_bars()
    bars.loc[DAYS[252], "high"] = 106.0  # +6% open profit
    got = codes(trade(stopped(100.0, 95.0), regime="bearish"), bars)
    assert "gave_back_profit" in got and "against_regime" in got


def test_market_drag_and_no_follow_through():
    bars = flat_bars()
    nifty = pd.Series(1000.0, index=DAYS)
    nifty.loc[DAYS[255] :] = 960.0  # -4% during the trade
    expired = Outcome("expired", DAYS[251], 100.0, DAYS[260], 99.0, -1.0, 10)
    got = codes(trade(expired), bars, nifty)
    assert "market_drag" in got and got[-1] == "no_follow_through"


def test_chased_entry_on_a_sell_uses_its_direction():
    bars = flat_bars()
    loss = Outcome("expired", DAYS[251], 90.0, DAYS[260], 91.0, -1.1, 10)  # sold 10% below the SMA
    assert "chased_entry" in codes(trade(loss, direction="SELL"), bars)


def test_unexplained_loss_falls_back_to_stock_specific():
    bars = flat_bars(spread=0.2)
    assert codes(trade(stopped(100.0, 95.0)), bars) == ["stock_specific"]


def test_reason_text_carries_the_numbers():
    bars = flat_bars()
    bars.loc[DAYS[252], "high"] = 106.0
    texts = [r.text for r in loss_reasons(trade(stopped(100.0, 95.0)), bars, features(bars), None)]
    assert any("Was up 6.0%" in t for t in texts)


@pytest.mark.parametrize("regime", ["bullish", "neutral", "unknown"])
def test_buy_is_not_against_a_non_bearish_regime(regime):
    assert "against_regime" not in codes(trade(stopped(100.0, 95.0), regime=regime), flat_bars())
