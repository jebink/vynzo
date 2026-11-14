from datetime import date

import pandas as pd
from fundamentals_worker.statements.yahoo import parse_annual, parse_dividends, parse_snapshot


def test_snapshot_keeps_finite_numbers_and_scales_debt_to_equity():
    snap = parse_snapshot(
        {
            "trailingPE": 45.8,
            "forwardPE": float("nan"),
            "totalDebt": 852000000,
            "debtToEquity": 32.4,
            "priceToBook": "Infinity",
            "heldPercentInsiders": 0.54,
            "currentRatio": True,
        }
    )
    assert snap["trailing_pe"] == 45.8 and snap["total_debt"] == 852000000.0
    assert snap["forward_pe"] is None and snap["price_to_book"] is None
    assert snap["current_ratio"] is None  # booleans are not numbers
    assert round(snap["debt_to_equity"], 3) == 0.324
    assert snap["insider_pct"] == 0.54 and snap["revenue_ttm"] is None


def test_annual_merges_income_and_balance_sheet_by_fiscal_year():
    y26, y25, y24 = (pd.Timestamp(d) for d in ("2026-03-31", "2025-03-31", "2024-03-31"))
    income = pd.DataFrame(
        {y26: [300.0, 60.0, 1.0], y25: [250.0, float("nan"), 2.0]},
        index=["Total Revenue", "Net Income", "EBIT"],
    )
    balance = pd.DataFrame({y26: [40.0], y25: [55.0], y24: [70.0]}, index=["Total Debt"])
    assert parse_annual(income, balance) == [
        (date(2024, 3, 31), None, None, 70.0),
        (date(2025, 3, 31), 250.0, None, 55.0),
        (date(2026, 3, 31), 300.0, 60.0, 40.0),
    ]
    assert parse_annual(income) == [
        (date(2025, 3, 31), 250.0, None, None),
        (date(2026, 3, 31), 300.0, 60.0, None),
    ]
    assert parse_annual(pd.DataFrame()) == [] and parse_annual(None) == []


def test_dividends_keep_recent_positive_payouts():
    s = pd.Series(
        [1.0, 0.0, 0.9, 1.95],
        index=pd.to_datetime(["2020-01-10", "2025-01-10", "2025-08-14", "2026-03-06"]).tz_localize(
            "Asia/Kolkata"
        ),
    )
    assert parse_dividends(s, date(2026, 11, 15)) == [
        (date(2025, 8, 14), 0.9),
        (date(2026, 3, 6), 1.95),
    ]
    assert parse_dividends(pd.Series(dtype=float), date(2026, 11, 15)) == []
